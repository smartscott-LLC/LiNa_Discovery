"""LocalDirectProvider — LINA's voice through libllama.so via ctypes.

Loads the local Qwen2-VL-2B model directly through llama.cpp's C API
with no HTTP server. Every generation wipes the KV cache afterward so
the model retains nothing between turns — LINA's memory system (Dragonfly
+ Postgres) handles all retention.

The model is a tool. She commands it like a CLI command.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import threading
from collections.abc import AsyncIterator
from typing import Any

from .base import AIProvider

log = logging.getLogger("lina.voice.local")

# ── Default paths ────────────────────────────────────────────────────────────
DEFAULT_MODEL_PATH = "/home/server/models/lina-local/Qwen2-VL-2B-Instruct-Q6_K.gguf"
DEFAULT_LIB_PATH = "libllama.so"
DEFAULT_N_CTX = 4096     # context window per turn (wiped after each)
DEFAULT_N_PREDICT = -1    # -1 = unlimited (stop at EOS/EOT)
DEFAULT_N_GPU_LAYERS = 0  # CPU only
DEFAULT_N_THREADS = 4     # reasonable default for the Dell laptop

# ── ctypes struct definitions ────────────────────────────────────────────────

class LlamaBatch(ctypes.Structure):
    """struct llama_batch — the input to llama_decode."""
    _fields_ = [
        ("n_tokens", ctypes.c_int32),
        ("token", ctypes.POINTER(ctypes.c_int32)),
        ("embd", ctypes.c_void_p),
        ("pos", ctypes.c_void_p),
        ("n_seq_id", ctypes.c_void_p),
        ("seq_id", ctypes.c_void_p),
        ("logits", ctypes.c_void_p),
    ]


class LlamaModelParams(ctypes.Structure):
    """struct llama_model_params — controls model loading."""
    _fields_ = [
        ("devices", ctypes.c_void_p),
        ("tensor_buft_overrides", ctypes.c_void_p),
        ("n_gpu_layers", ctypes.c_int32),
        ("split_mode", ctypes.c_int32),
        ("load_mode", ctypes.c_int32),
        ("main_gpu", ctypes.c_int32),
        ("tensor_split", ctypes.c_void_p),
        ("progress_callback", ctypes.c_void_p),
        ("progress_callback_user_data", ctypes.c_void_p),
        ("kv_overrides", ctypes.c_void_p),
        ("vocab_only", ctypes.c_bool),
        ("check_tensors", ctypes.c_bool),
        ("use_extra_bufts", ctypes.c_bool),
        ("no_host", ctypes.c_bool),
        ("no_alloc", ctypes.c_bool),
        ("load_mtp", ctypes.c_bool),
    ]


class LlamaContextParams(ctypes.Structure):
    """struct llama_context_params — must match llama.h exactly (37 fields).

    Verified against /home/server/llama.cpp/include/llama.h line 351.
    Keep the booleans together at the end, matching the C layout — the
    comment in llama.h says this is intentional to avoid misalignment
    during copy-by-value.
    """
    _fields_ = [
        ("n_ctx", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint32),
        ("n_ubatch", ctypes.c_uint32),
        ("n_seq_max", ctypes.c_uint32),
        ("n_rs_seq", ctypes.c_uint32),
        ("n_outputs_max", ctypes.c_uint32),
        ("n_outputs_max_per_seq", ctypes.c_uint32),
        ("n_threads", ctypes.c_int32),
        ("n_threads_batch", ctypes.c_int32),
        ("ctx_type", ctypes.c_int32),
        ("rope_scaling_type", ctypes.c_int32),
        ("pooling_type", ctypes.c_int32),
        ("attention_type", ctypes.c_int32),
        ("flash_attn_type", ctypes.c_int32),
        ("rope_freq_base", ctypes.c_float),
        ("rope_freq_scale", ctypes.c_float),
        ("yarn_ext_factor", ctypes.c_float),
        ("yarn_attn_factor", ctypes.c_float),
        ("yarn_beta_fast", ctypes.c_float),
        ("yarn_beta_slow", ctypes.c_float),
        ("yarn_orig_ctx", ctypes.c_uint32),
        ("defrag_thold", ctypes.c_float),
        ("cb_eval", ctypes.c_void_p),
        ("cb_eval_user_data", ctypes.c_void_p),
        ("type_k", ctypes.c_int32),
        ("type_v", ctypes.c_int32),
        ("abort_callback", ctypes.c_void_p),
        ("abort_callback_data", ctypes.c_void_p),
        ("embeddings", ctypes.c_bool),
        ("offload_kqv", ctypes.c_bool),
        ("no_perf", ctypes.c_bool),
        ("op_offload", ctypes.c_bool),
        ("swa_full", ctypes.c_bool),
        ("kv_unified", ctypes.c_bool),
        ("samplers", ctypes.c_void_p),
        ("n_samplers", ctypes.c_size_t),
        ("ctx_other", ctypes.c_void_p),
    ]


class LlamaSamplerChainParams(ctypes.Structure):
    """struct llama_sampler_chain_params."""
    _fields_ = [
        ("no_perf", ctypes.c_bool),
    ]


class LlamaChatMessage(ctypes.Structure):
    """struct llama_chat_message — role/content pair for chat template."""
    _fields_ = [
        ("role", ctypes.c_char_p),
        ("content", ctypes.c_char_p),
    ]


# ── Provider ─────────────────────────────────────────────────────────────────

class LocalDirectProvider(AIProvider):
    """LINA's voice on the carve — llama.cpp via ctypes, no HTTP server.

    Every generation is a clean slate: the KV cache is cleared after every
    turn, so the model retains nothing. LINA's memory system (Dragonfly +
    Postgres) handles all retention.

    Attributes:
        name:  ``"local"`` — matches ``AI_PROVIDER=local``
        label: Human-readable description for logs
    """

    name = "local"
    label = "Local (llama.cpp direct ctypes)"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        n_ctx: int = DEFAULT_N_CTX,
        n_predict: int = DEFAULT_N_PREDICT,
        n_gpu_layers: int = DEFAULT_N_GPU_LAYERS,
        n_threads: int = DEFAULT_N_THREADS,
    ) -> None:
        super().__init__(base_url=base_url, model=model)
        self._model_path = (
            model
            or os.getenv("LOCAL_MODEL_PATH")
            or DEFAULT_MODEL_PATH
        )
        self._n_ctx = n_ctx
        self._n_predict = n_predict
        self._n_gpu_layers = n_gpu_layers
        self._n_threads = n_threads

        # State
        self._lib: ctypes.CDLL | None = None
        self._model: ctypes.c_void_p | None = None
        self._vocab: ctypes.c_void_p | None = None
        self._ctx: ctypes.c_void_p | None = None
        self._sampler: ctypes.c_void_p | None = None
        self._loaded = False
        self._lock = threading.Lock()

        # Template (cached from model)
        self._chat_template: str | None = None

        log.info("[local] provider created (model=%s, n_ctx=%d, n_threads=%d)",
                 self._model_path, self._n_ctx, self._n_threads)

    # ── Public API (AIProvider contract) ─────────────────────────────────────

    async def warmup(self) -> None:
        """Load the model eagerly. Idempotent — safe to call multiple times.

        Runs the blocking ``_ensure_loaded()`` in a thread pool executor so
        the event loop stays responsive. After the model is loaded, the KV
        cache is cleared so every turn starts clean.
        """
        if self._loaded:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._ensure_loaded)
        if self._loaded and self._ctx is not None and self._lib is not None:
            with self._lock:
                mem = self._lib.llama_get_memory(self._ctx)
                if mem:
                    self._lib.llama_memory_clear(mem, True)
        log.info("[local] warmup complete")

    async def generate(
        self,
        system: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        """Generate a response through the local model.

        Runs in a thread pool executor to avoid blocking the event loop.
        The KV cache is wiped after every generation.
        """
        self._ensure_loaded()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._generate_sync, system, messages, kwargs,
        )

    async def generate_stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming not supported for direct local model — yield whole response."""
        text = await self.generate(system, messages, **kwargs)
        if text:
            yield text

    async def aclose(self) -> None:
        """Free model, context, sampler, and backend. Idempotent."""
        if not self._loaded:
            return
        with self._lock:
            if self._sampler:
                self._lib.llama_sampler_free(self._sampler)  # type: ignore[union-attr]
                self._sampler = None
            if self._ctx:
                self._lib.llama_free(self._ctx)  # type: ignore[union-attr]
                self._ctx = None
            if self._model:
                self._lib.llama_model_free(self._model)  # type: ignore[union-attr]
                self._model = None
            self._lib.llama_backend_free()  # type: ignore[union-attr]
            self._loaded = False
        log.info("[local] provider shut down cleanly")

    # ── Internal: lazy loading ───────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        """Load the library and model on first use."""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._load_library()
            self._load_model()
            self._loaded = True

    def _load_library(self) -> None:
        """Load libllama.so and bind all function signatures."""
        lib_path = os.getenv("LLAMA_LIB_PATH") or DEFAULT_LIB_PATH
        self._lib = ctypes.CDLL(lib_path)

        lib = self._lib

        # ── Backend ──────────────────────────────────────────────────────
        lib.llama_backend_init.argtypes = ()
        lib.llama_backend_init.restype = None
        lib.llama_backend_free.argtypes = ()
        lib.llama_backend_free.restype = None

        # ── Model ────────────────────────────────────────────────────────
        lib.llama_model_default_params.argtypes = ()
        lib.llama_model_default_params.restype = LlamaModelParams

        lib.llama_model_load_from_file.argtypes = (
            ctypes.c_char_p, LlamaModelParams,
        )
        lib.llama_model_load_from_file.restype = ctypes.c_void_p

        lib.llama_model_free.argtypes = (ctypes.c_void_p,)
        lib.llama_model_free.restype = None

        lib.llama_model_get_vocab.argtypes = (ctypes.c_void_p,)
        lib.llama_model_get_vocab.restype = ctypes.c_void_p

        lib.llama_model_chat_template.argtypes = (
            ctypes.c_void_p, ctypes.c_char_p,
        )
        lib.llama_model_chat_template.restype = ctypes.c_char_p

        lib.llama_model_has_encoder.argtypes = (ctypes.c_void_p,)
        lib.llama_model_has_encoder.restype = ctypes.c_bool

        lib.llama_model_decoder_start_token.argtypes = (ctypes.c_void_p,)
        lib.llama_model_decoder_start_token.restype = ctypes.c_int32

        # ── Context ──────────────────────────────────────────────────────
        lib.llama_context_default_params.argtypes = ()
        lib.llama_context_default_params.restype = LlamaContextParams

        lib.llama_init_from_model.argtypes = (
            ctypes.c_void_p, LlamaContextParams,
        )
        lib.llama_init_from_model.restype = ctypes.c_void_p

        lib.llama_free.argtypes = (ctypes.c_void_p,)
        lib.llama_free.restype = None

        lib.llama_get_memory.argtypes = (ctypes.c_void_p,)
        lib.llama_get_memory.restype = ctypes.c_void_p

        lib.llama_set_n_threads.argtypes = (
            ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32,
        )
        lib.llama_set_n_threads.restype = None

        # ── Memory (KV cache) ────────────────────────────────────────────
        lib.llama_memory_clear.argtypes = (ctypes.c_void_p, ctypes.c_bool)
        lib.llama_memory_clear.restype = None

        # ── Batch ────────────────────────────────────────────────────────
        lib.llama_batch_get_one.argtypes = (
            ctypes.POINTER(ctypes.c_int32), ctypes.c_int32,
        )
        lib.llama_batch_get_one.restype = LlamaBatch

        # ── Inference ────────────────────────────────────────────────────
        lib.llama_decode.argtypes = (ctypes.c_void_p, LlamaBatch)
        lib.llama_decode.restype = ctypes.c_int32

        lib.llama_encode.argtypes = (ctypes.c_void_p, LlamaBatch)
        lib.llama_encode.restype = ctypes.c_int32

        # ── Sampler ──────────────────────────────────────────────────────
        lib.llama_sampler_chain_default_params.argtypes = ()
        lib.llama_sampler_chain_default_params.restype = LlamaSamplerChainParams

        lib.llama_sampler_chain_init.argtypes = (LlamaSamplerChainParams,)
        lib.llama_sampler_chain_init.restype = ctypes.c_void_p

        lib.llama_sampler_chain_add.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p,
        )
        lib.llama_sampler_chain_add.restype = None

        lib.llama_sampler_init_greedy.argtypes = ()
        lib.llama_sampler_init_greedy.restype = ctypes.c_void_p

        lib.llama_sampler_sample.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32,
        )
        lib.llama_sampler_sample.restype = ctypes.c_int32

        lib.llama_sampler_free.argtypes = (ctypes.c_void_p,)
        lib.llama_sampler_free.restype = None

        # ── Tokenization ─────────────────────────────────────────────────
        lib.llama_tokenize.argtypes = (
            ctypes.c_void_p,           # vocab
            ctypes.c_char_p,           # text
            ctypes.c_int32,            # text_len
            ctypes.POINTER(ctypes.c_int32),  # tokens
            ctypes.c_int32,            # n_tokens_max
            ctypes.c_bool,             # add_special
            ctypes.c_bool,             # parse_special
        )
        lib.llama_tokenize.restype = ctypes.c_int32

        lib.llama_token_to_piece.argtypes = (
            ctypes.c_void_p,           # vocab
            ctypes.c_int32,            # token
            ctypes.c_char_p,           # buf
            ctypes.c_int32,            # length
            ctypes.c_int32,            # lstrip
            ctypes.c_bool,             # special
        )
        lib.llama_token_to_piece.restype = ctypes.c_int32

        # ── Vocab helpers ────────────────────────────────────────────────
        lib.llama_vocab_is_eog.argtypes = (
            ctypes.c_void_p, ctypes.c_int32,
        )
        lib.llama_vocab_is_eog.restype = ctypes.c_bool

        lib.llama_vocab_bos.argtypes = (ctypes.c_void_p,)
        lib.llama_vocab_bos.restype = ctypes.c_int32

        # ── Chat template ────────────────────────────────────────────────
        lib.llama_chat_apply_template.argtypes = (
            ctypes.c_char_p,                         # tmpl
            ctypes.POINTER(LlamaChatMessage),         # chat
            ctypes.c_size_t,                          # n_msg
            ctypes.c_bool,                            # add_ass
            ctypes.c_char_p,                          # buf
            ctypes.c_int32,                          # length
        )
        lib.llama_chat_apply_template.restype = ctypes.c_int32

        log.info("[local] libllama.so loaded from %s", lib_path)

    def _load_model(self) -> None:
        """Initialize backend, load model, create context + sampler."""
        lib = self._lib

        # 1. Initialize backend
        lib.llama_backend_init()
        log.info("[local] llama backend initialized")

        # 2. Load model
        model_path = self._model_path.encode("utf-8")
        if not os.path.exists(self._model_path):
            raise FileNotFoundError(
                f"Local model not found at {self._model_path}. "
                "Set LOCAL_MODEL_PATH or check the carve."
            )

        model_params = lib.llama_model_default_params()
        model_params.n_gpu_layers = self._n_gpu_layers

        self._model = lib.llama_model_load_from_file(model_path, model_params)
        if not self._model:
            raise RuntimeError(
                f"Failed to load model from {self._model_path}"
            )
        log.info("[local] model loaded from %s", self._model_path)

        # 3. Get vocab
        self._vocab = lib.llama_model_get_vocab(self._model)
        if not self._vocab:
            raise RuntimeError("Failed to get model vocab")

        # 4. Cache chat template
        tmpl = lib.llama_model_chat_template(self._model, None)
        self._chat_template = tmpl.decode("utf-8") if tmpl else None
        log.info("[local] chat template: %s",
                 self._chat_template[:80] if self._chat_template else "default")

        # 5. Create context
        ctx_params = lib.llama_context_default_params()
        ctx_params.n_ctx = self._n_ctx
        ctx_params.n_batch = self._n_ctx  # batch can be full context
        ctx_params.n_ubatch = self._n_ctx
        ctx_params.n_threads = self._n_threads
        ctx_params.n_threads_batch = self._n_threads

        self._ctx = lib.llama_init_from_model(self._model, ctx_params)
        if not self._ctx:
            lib.llama_model_free(self._model)
            self._model = None
            raise RuntimeError("Failed to create llama context")
        log.info("[local] context created (n_ctx=%d, n_threads=%d)",
                 self._n_ctx, self._n_threads)

        # 6. Set thread count explicitly
        lib.llama_set_n_threads(self._ctx, self._n_threads, self._n_threads)

        # 7. Create sampler chain (greedy for now)
        sparams = lib.llama_sampler_chain_default_params()
        # Force no_perf to False to avoid struct layout issues
        sparams.no_perf = False
        self._sampler = lib.llama_sampler_chain_init(sparams)
        if not self._sampler:
            raise RuntimeError("Failed to create sampler chain")

        greedy = lib.llama_sampler_init_greedy()
        if not greedy:
            raise RuntimeError("Failed to create greedy sampler")
        lib.llama_sampler_chain_add(self._sampler, greedy)
        log.info("[local] greedy sampler ready")

    # ── Internal: synchronous generation ─────────────────────────────────────

    def _generate_sync(
        self,
        system: str,
        messages: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> str:
        """Synchronous generation — runs in a thread pool executor.

        **Must be called while holding the lock.**
        """
        lib = self._lib
        model = self._model
        vocab = self._vocab
        ctx = self._ctx
        sampler = self._sampler
        assert lib is not None
        assert model is not None
        assert vocab is not None
        assert ctx is not None
        assert sampler is not None

        # 1. Build prompt from system + messages using chat template
        prompt = self._build_prompt(system, messages)
        if not prompt:
            return ""

        prompt_bytes = prompt.encode("utf-8")

        # 2. Tokenize the prompt
        # First call gets the required token count (negative = need that many)
        n_tokens_needed = lib.llama_tokenize(
            vocab, prompt_bytes, len(prompt_bytes),
            None, 0, True, True,
        )
        if n_tokens_needed <= 0:
            n_tokens = -n_tokens_needed
        else:
            n_tokens = n_tokens_needed

        if n_tokens > self._n_ctx:
            log.warning("[local] prompt truncated: %d tokens > %d context",
                        n_tokens, self._n_ctx)
            n_tokens = self._n_ctx

        # Allocate token array
        tokens = (ctypes.c_int32 * n_tokens)()
        actual = lib.llama_tokenize(
            vocab, prompt_bytes, len(prompt_bytes),
            tokens, n_tokens, True, True,
        )
        if actual < 0:
            log.error("[local] tokenization failed: %d", actual)
            return "_LINA has no voice right now."

        n_prompt_tokens = actual

        # 3. Create batch for prompt
        batch = lib.llama_batch_get_one(tokens, n_prompt_tokens)

        # 4. Handle encoder models (vision encoder for Qwen2-VL)
        if lib.llama_model_has_encoder(model):
            if lib.llama_encode(ctx, batch):
                log.error("[local] encode failed")
                return "_LINA has no voice right now."
            dec_start = lib.llama_model_decoder_start_token(model)
            if dec_start < 0:
                dec_start = lib.llama_vocab_bos(vocab)
            if dec_start < 0:
                dec_start = 1  # fallback BOS
            dec_token = (ctypes.c_int32 * 1)(dec_start)
            batch = lib.llama_batch_get_one(dec_token, 1)

        # 5. Decode loop
        output_pieces: list[str] = []
        n_pos = 0
        n_decode = 0
        max_tokens = kwargs.get("max_tokens") or self._n_predict
        if max_tokens is None or max_tokens < 0:
            max_tokens = self._n_ctx * 2  # safety limit

        # 128-byte buffer for token-to-piece conversion
        buf = ctypes.create_string_buffer(128)

        while n_pos + batch.n_tokens < n_prompt_tokens + max_tokens + 1:
            # Decode batch
            if lib.llama_decode(ctx, batch):
                log.warning("[local] decode failed at position %d", n_pos)
                break

            n_pos += batch.n_tokens

            # Sample next token
            new_token = lib.llama_sampler_sample(sampler, ctx, -1)

            # Check for end of generation
            if lib.llama_vocab_is_eog(vocab, new_token):
                break

            # Convert token to piece
            n_chars = lib.llama_token_to_piece(
                vocab, new_token, buf, len(buf), 0, True,
            )
            if n_chars < 0:
                # Buffer too small? Try again with a larger buffer
                n_chars = lib.llama_token_to_piece(
                    vocab, new_token, buf, len(buf) * 2, 0, True,
                )
                if n_chars < 0:
                    break

            output_pieces.append(buf.value.decode("utf-8", errors="replace"))

            # Prepare next batch with the sampled token
            next_token = (ctypes.c_int32 * 1)(new_token)
            batch = lib.llama_batch_get_one(next_token, 1)
            n_decode += 1

            # Safety limit
            if n_decode > max_tokens:
                log.warning("[local] hit max tokens limit (%d)", max_tokens)
                break

        # 6. Clear KV cache — model retains NOTHING between turns
        mem = lib.llama_get_memory(ctx)
        if mem:
            lib.llama_memory_clear(mem, True)

        response = "".join(output_pieces).strip()
        log.info("[local] generated %d tokens in %d decode steps",
                 n_prompt_tokens, n_decode)

        if not response:
            return "_LINA has no voice right now."

        return response

    # ── Internal: prompt building ────────────────────────────────────────────

    def _build_prompt(self, system: str, messages: list[dict[str, Any]]) -> str:
        """Build a chat-formatted prompt using the model's chat template.

        If the model has a built-in template (llama_chat_apply_template),
        we use that. Otherwise we fall back to a simple Qwen-compatible format.
        """
        lib = self._lib
        if lib is None or self._chat_template is None:
            return self._fallback_prompt(system, messages)

        # Build llama_chat_message array
        n_msgs = len(messages)
        if system:
            n_msgs += 1  # system message goes first

        msg_array = (LlamaChatMessage * n_msgs)()
        idx = 0

        if system:
            msg_array[idx] = LlamaChatMessage(
                b"system", system.encode("utf-8"),
            )
            idx += 1

        for msg in messages:
            role = msg.get("role", "user").encode("utf-8")
            content = msg.get("content", "").encode("utf-8")
            msg_array[idx] = LlamaChatMessage(role, content)
            idx += 1

        # Apply template with 2x size estimate
        template = self._chat_template.encode("utf-8")
        est_size = max(4096, sum(len(m.content or b"") for m in msg_array) * 2)
        buf = ctypes.create_string_buffer(est_size)

        needed = lib.llama_chat_apply_template(
            template, msg_array, n_msgs, True, buf, len(buf),
        )

        if needed < 0:
            log.warning("[local] chat template failed, using fallback")
            return self._fallback_prompt(system, messages)

        if needed > len(buf):
            # Buffer too small — reallocate
            buf = ctypes.create_string_buffer(needed + 1)
            lib.llama_chat_apply_template(
                template, msg_array, n_msgs, True, buf, len(buf),
            )

        result = buf.value.decode("utf-8", errors="replace")
        return result

    def _fallback_prompt(self, system: str, messages: list[dict[str, Any]]) -> str:
        """Fallback prompt format when chat template is unavailable.

        Uses a simple Qwen-compatible format:
        <|im_start|>system
        {system}<|im_end|>
        <|im_start|>user
        {message}<|im_end|>
        <|im_start|>assistant
        """
        parts: list[str] = []
        if system:
            parts.append(f"<|im_start|>system\n{system}<|im_end|>")
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)