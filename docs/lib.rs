// Float32Array is only available when compiling for the browser (wasm32).
// On native targets the `#[wasm_bindgen]` attribute is a no-op, so all
// String-returning exports compile as normal Rust functions.  Only the
// `fibonacci_sphere_points` export changes signature: it returns a
// `Float32Array` for WASM and a `Vec<f32>` for native.
#[cfg(target_arch = "wasm32")]
use js_sys::Float32Array;
use wasm_bindgen::prelude::*;

// ---------------------------------------------------------------------------
// Letter color palette — one per Hebrew letter (22 total), normalized RGB.
// Matches the canonical AnaStone color table defined in visualize.py.
// ---------------------------------------------------------------------------
const LETTER_COLORS_RGB: [[f32; 3]; 22] = [
    [0.902, 0.224, 0.275], // 0  Aleph  #E63946
    [0.957, 0.635, 0.380], // 1  Bet    #F4A261
    [0.914, 0.769, 0.416], // 2  Gimel  #E9C46A
    [0.165, 0.616, 0.561], // 3  Dalet  #2A9D8F
    [0.149, 0.275, 0.325], // 4  He     #264653
    [0.271, 0.482, 0.616], // 5  Vav    #457B9D
    [0.659, 0.855, 0.863], // 6  Zayin  #A8DADC
    [0.282, 0.792, 0.894], // 7  Chet   #48CAE4
    [0.008, 0.243, 0.541], // 8  Tet    #023E8A
    [0.482, 0.176, 0.545], // 9  Yod    #7B2D8B
    [0.780, 0.490, 1.000], // 10 Kaf    #C77DFF
    [1.000, 0.420, 0.420], // 11 Lamed  #FF6B6B
    [1.000, 0.851, 0.239], // 12 Mem    #FFD93D
    [0.420, 0.796, 0.467], // 13 Nun    #6BCB77
    [0.302, 0.588, 1.000], // 14 Samekh #4D96FF
    [1.000, 0.624, 0.110], // 15 Ayin   #FF9F1C
    [1.000, 0.749, 0.412], // 16 Pe     #FFBF69
    [0.796, 0.953, 0.941], // 17 Tsadi  #CBF3F0
    [0.180, 0.769, 0.714], // 18 Qof    #2EC4B6
    [0.906, 0.435, 0.3176], // 19 Resh   #E76F51  (R=231, G=111, B=81; 81/255 truncated to 4 dp)
    [0.945, 0.980, 0.933], // 20 Shin   #F1FAEE
    [0.659, 0.773, 0.627], // 21 Tav    #A8C5A0
];

// ---------------------------------------------------------------------------
// Fibonacci sphere — pure-Rust inner computation (no WASM types).
//
// Returns a flat Vec<f32> with layout: [x,y,z, r,g,b,  x,y,z, r,g,b, ...]
// Each group of 6 floats is one surface point with its Hebrew-letter color.
//
// total   — full canonical count (e.g. 2_200_000)
// radius  — sphere radius in inches (3.5 for the 7-inch Anasphere)
// stride  — sample every Nth point (1 = all, 22 = 100 000 pts for 2.2 M total)
// ---------------------------------------------------------------------------
pub fn fibonacci_sphere_inner(total: u32, radius: f32, stride: u32) -> Vec<f32> {
    let n = total as usize;
    // Guard: need at least 2 points for a well-defined Fibonacci distribution.
    // With n <= 1, n_m1 == 0 and the y formula produces NaN/Inf.
    if n <= 1 {
        return Vec::new();
    }
    let r = radius as f64;
    let s = stride.max(1) as usize;
    let golden_angle: f64 = std::f64::consts::PI * (3.0 - 5.0_f64.sqrt());

    let count = n.div_ceil(s);
    let mut data = vec![0f32; count * 6];
    let mut out = 0usize;
    let n_m1 = (n - 1) as f64;

    for i in (0..n).step_by(s) {
        let fi = i as f64;
        let y = 1.0 - 2.0 * fi / n_m1;
        let radial = (1.0 - y * y).max(0.0).sqrt();
        let theta = golden_angle * fi;

        data[out]     = (r * theta.cos() * radial) as f32;
        data[out + 1] = (r * y) as f32;
        data[out + 2] = (r * theta.sin() * radial) as f32;

        // Use the output-slot position (out/6) rather than the source index (i)
        // to assign Hebrew-letter colors.  When stride is a multiple of 22 every
        // sampled source index i satisfies i % 22 == 0, which would give all
        // points the same Aleph color.  The output counter always increments by
        // one per point, so (out/6) % 22 cycles through all 22 letters correctly.
        let c = &LETTER_COLORS_RGB[(out / 6) % 22];
        data[out + 3] = c[0];
        data[out + 4] = c[1];
        data[out + 5] = c[2];

        out += 6;
    }
    data.truncate(out);
    data
}

// ---------------------------------------------------------------------------
// WASM export — wraps fibonacci_sphere_inner, returns a JS Float32Array.
// Only compiled when targeting wasm32 (browser environment).
// ---------------------------------------------------------------------------
#[cfg(target_arch = "wasm32")]
#[wasm_bindgen]
pub fn fibonacci_sphere_points(total: u32, radius: f32, stride: u32) -> Float32Array {
    let data = fibonacci_sphere_inner(total, radius, stride);
    let arr = Float32Array::new_with_length(data.len() as u32);
    arr.copy_from(&data);
    arr
}

// ---------------------------------------------------------------------------
// Native export — same computation, returns Vec<f32> (no JS dependency).
// Used by the standalone anastone-wasm-engine CLI binary.
// ---------------------------------------------------------------------------
#[cfg(not(target_arch = "wasm32"))]
pub fn fibonacci_sphere_points(total: u32, radius: f32, stride: u32) -> Vec<f32> {
    fibonacci_sphere_inner(total, radius, stride)
}

// ---------------------------------------------------------------------------
// Key / score extraction helpers (mirrors src/lib.rs)
// ---------------------------------------------------------------------------

const KEY_FIELDS: &[&str] = &[
    "key", "id", "name", "label", "title", "text",
    "identifier", "word", "term", "token", "tag",
];
const SCORE_FIELDS: &[&str] = &[
    "score", "value", "weight", "rank", "priority",
    "rating", "confidence", "probability", "amount", "count",
];

fn wasm_extract_key(val: &serde_json::Value) -> String {
    if let Some(obj) = val.as_object() {
        for &f in KEY_FIELDS {
            if let Some(v) = obj.get(f) {
                return match v {
                    serde_json::Value::String(s) => s.clone(),
                    other => other.to_string(),
                };
            }
        }
        for (_, v) in obj.iter() {
            if let serde_json::Value::String(s) = v {
                return s.clone();
            }
        }
        if let Some((k, _)) = obj.iter().next() {
            return k.clone();
        }
    }
    match val {
        serde_json::Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

fn wasm_extract_score(val: &serde_json::Value) -> f64 {
    if let Some(obj) = val.as_object() {
        for &f in SCORE_FIELDS {
            if let Some(v) = obj.get(f) {
                if let Some(n) = v.as_f64() {
                    return n;
                }
            }
        }
        for (_, v) in obj.iter() {
            if let Some(n) = v.as_f64() {
                return n;
            }
        }
    }
    val.as_f64().unwrap_or(0.0)
}

// ---------------------------------------------------------------------------
// Delimiter-separated score extraction
// ---------------------------------------------------------------------------
fn extract_delimited_score(parts: &[&str]) -> f64 {
    // Try col 1, then col 0, then any column
    parts
        .get(1)
        .and_then(|v| v.trim().parse::<f64>().ok())
        .or_else(|| parts.first().and_then(|v| v.trim().parse::<f64>().ok()))
        .unwrap_or(0.0)
}

fn extract_delimited_key<'a>(parts: &[&'a str]) -> &'a str {
    if parts.len() >= 2 {
        // If first column is NOT numeric, use it as key
        if parts[0].trim().parse::<f64>().is_err() {
            return parts[0].trim();
        }
        // Otherwise use second column
        return parts[1].trim();
    }
    parts.first().map(|s| s.trim()).unwrap_or("")
}

// ---------------------------------------------------------------------------
// Input validation and preview
//
// Parses up to max_rows records from the supplied bytes.
// Handles: JSON array, JSON lines, TOML, TSV, CSV, plain text.
// Returns a JSON string:
// {
//   "valid": bool,
//   "format": "JSON" | "JSON_ARRAY" | "CSV" | "TSV" | "TOML" | "TEXT" | "MIXED" | "UNKNOWN",
//   "total_rows": N,
//   "json_rows": N,
//   "csv_rows": N,
//   "error_rows": N,
//   "preview": [{"line":1,"source":"JSON","key":"...","score":0.5}, ...]
// }
// ---------------------------------------------------------------------------
#[wasm_bindgen]
pub fn validate_and_preview(data: &[u8], max_rows: u32) -> String {
    let max = max_rows as usize;
    let mut preview: Vec<serde_json::Value> = Vec::new();
    let mut json_count = 0usize;
    let mut csv_count = 0usize;
    let mut total = 0usize;
    let mut errors = 0usize;
    let format_label;

    // ------------------------------------------------------------------
    // 1. JSON array (whole-file)
    // ------------------------------------------------------------------
    let first_nonws = data.iter().copied().find(|b| !b.is_ascii_whitespace());
    if first_nonws == Some(b'[') {
        if let Ok(serde_json::Value::Array(arr)) = serde_json::from_slice::<serde_json::Value>(data) {
            format_label = "JSON_ARRAY";
            for (i, val) in arr.iter().enumerate() {
                total += 1;
                json_count += 1;
                if preview.len() < max {
                    preview.push(serde_json::json!({
                        "line": i + 1,
                        "source": "JSON",
                        "key": wasm_extract_key(val),
                        "score": wasm_extract_score(val),
                    }));
                }
            }
            return build_preview_result(format_label, total, json_count, csv_count, errors, &preview);
        }
    }

    // ------------------------------------------------------------------
    // 2. YAML (whole-file) — handles both `---` marker and bare mappings
    // ------------------------------------------------------------------
    if data.starts_with(b"---") || looks_like_yaml_wasm(data) {
        if let Ok(yval) = serde_yaml::from_slice::<serde_yaml::Value>(data) {
            if let Ok(json_str) = serde_json::to_string(&yval) {
                if let Ok(jval) = serde_json::from_str::<serde_json::Value>(&json_str) {
                    let items: Vec<serde_json::Value> = match &jval {
                        serde_json::Value::Array(arr) => arr.clone(),
                        serde_json::Value::Object(map) => {
                            map.iter()
                                .map(|(k, v)| {
                                    serde_json::json!({"key": k, "score": v.as_f64().unwrap_or(0.0)})
                                })
                                .collect()
                        }
                        _ => vec![jval.clone()],
                    };
                    if !items.is_empty() {
                        format_label = "YAML";
                        for (i, val) in items.iter().enumerate() {
                            total += 1;
                            json_count += 1;
                            if preview.len() < max {
                                preview.push(serde_json::json!({
                                    "line": i + 1,
                                    "source": "YAML",
                                    "key": wasm_extract_key(val),
                                    "score": wasm_extract_score(val),
                                }));
                            }
                        }
                        return build_preview_result(format_label, total, json_count, csv_count, errors, &preview);
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------
    // 3. TOML (whole-file)
    // ------------------------------------------------------------------
    if let Ok(s) = std::str::from_utf8(data) {
        if looks_like_toml_wasm(data) {
            if let Ok(tval) = toml::from_str::<toml::Value>(s) {
                if let Ok(json_str) = serde_json::to_string(&tval) {
                    if let Ok(jval) = serde_json::from_str::<serde_json::Value>(&json_str) {
                        format_label = "TOML";
                        let items: Vec<serde_json::Value> = match &jval {
                            serde_json::Value::Array(arr) => arr.clone(),
                            serde_json::Value::Object(map) => {
                                // Check for array-of-tables
                                let mut out = Vec::new();
                                for (_, v) in map.iter() {
                                    if let serde_json::Value::Array(arr) = v {
                                        out.extend(arr.clone());
                                    }
                                }
                                if out.is_empty() {
                                    // Flat table: each entry is a fragment
                                    map.iter()
                                        .map(|(k, v)| serde_json::json!({"key": k, "score": v.as_f64().unwrap_or(0.0)}))
                                        .collect()
                                } else {
                                    out
                                }
                            }
                            _ => vec![jval.clone()],
                        };
                        for (i, val) in items.iter().enumerate() {
                            total += 1;
                            json_count += 1;
                            if preview.len() < max {
                                preview.push(serde_json::json!({
                                    "line": i + 1,
                                    "source": "TOML",
                                    "key": wasm_extract_key(val),
                                    "score": wasm_extract_score(val),
                                }));
                            }
                        }
                        return build_preview_result(format_label, total, json_count, csv_count, errors, &preview);
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------
    // 4. Line-by-line: JSON objects, TSV, CSV, plain text
    // ------------------------------------------------------------------
    let mut tsv_count = 0usize;
    let mut text_count = 0usize;

    for (line_no, raw_line) in data.split(|&b| b == b'\n').enumerate() {
        let trimmed: Vec<u8> = raw_line
            .iter()
            .copied()
            .skip_while(|b| b.is_ascii_whitespace())
            .collect();
        let trimmed = if trimmed.ends_with(b"\r") {
            trimmed[..trimmed.len() - 1].to_vec()
        } else {
            trimmed
        };
        if trimmed.is_empty() {
            continue;
        }
        total += 1;

        if trimmed.first() == Some(&b'{') {
            // JSON object
            match serde_json::from_slice::<serde_json::Value>(&trimmed) {
                Ok(val) => {
                    json_count += 1;
                    if preview.len() < max {
                        preview.push(serde_json::json!({
                            "line": line_no + 1,
                            "source": "JSON",
                            "key": wasm_extract_key(&val),
                            "score": wasm_extract_score(&val),
                        }));
                    }
                }
                Err(_) => { errors += 1; }
            }
        } else if trimmed.contains(&b'\t') {
            // TSV
            let s = String::from_utf8_lossy(&trimmed);
            let parts: Vec<&str> = s.splitn(8, '\t').collect();
            let key = extract_delimited_key(&parts).to_string();
            let score = extract_delimited_score(&parts);
            tsv_count += 1;
            if preview.len() < max {
                preview.push(serde_json::json!({
                    "line": line_no + 1,
                    "source": "TSV",
                    "key": key,
                    "score": score,
                }));
            }
        } else if trimmed.contains(&b',') {
            // CSV
            let s = String::from_utf8_lossy(&trimmed);
            let parts: Vec<&str> = s.splitn(8, ',').collect();
            let key = extract_delimited_key(&parts).to_string();
            let score = extract_delimited_score(&parts);
            csv_count += 1;
            if preview.len() < max {
                preview.push(serde_json::json!({
                    "line": line_no + 1,
                    "source": "CSV",
                    "key": key,
                    "score": score,
                }));
            }
        } else {
            // Plain text
            let text = String::from_utf8_lossy(&trimmed).into_owned();
            text_count += 1;
            if preview.len() < max {
                preview.push(serde_json::json!({
                    "line": line_no + 1,
                    "source": "TEXT",
                    "key": text,
                    "score": 0.0,
                }));
            }
        }
    }

    // Determine format label from line-by-line results
    let line_types = (json_count > 0) as u8
        + (csv_count > 0) as u8
        + (tsv_count > 0) as u8
        + (text_count > 0) as u8;
    format_label = if line_types > 1 {
        "MIXED"
    } else if json_count > 0 {
        "JSON"
    } else if tsv_count > 0 {
        "TSV"
    } else if csv_count > 0 {
        "CSV"
    } else if text_count > 0 {
        "TEXT"
    } else {
        "UNKNOWN"
    };

    // csv_count in the result includes TSV for backward compat display
    build_preview_result(format_label, total, json_count, csv_count + tsv_count, errors, &preview)
}

fn looks_like_toml_wasm(input: &[u8]) -> bool {
    let s = match std::str::from_utf8(input) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let mut total = 0usize;
    let mut toml_like = 0usize;
    for line in s.lines() {
        let l = line.trim();
        if l.is_empty() || l.starts_with('#') {
            continue;
        }
        total += 1;
        if (l.starts_with('[') && l.ends_with(']')) || l.contains(" = ") {
            toml_like += 1;
        }
    }
    total >= 2 && toml_like * 2 >= total
}

fn looks_like_yaml_wasm(input: &[u8]) -> bool {
    let s = match std::str::from_utf8(input) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let mut total = 0usize;
    let mut yaml_like = 0usize;
    for line in s.lines() {
        let l = line.trim();
        if l.is_empty() || l.starts_with('#') {
            continue;
        }
        total += 1;
        if l.contains(": ") && !l.contains(" = ") {
            yaml_like += 1;
        }
    }
    total >= 2 && yaml_like * 2 >= total
}

fn build_preview_result(
    format: &str,
    total: usize,
    json_rows: usize,
    csv_rows: usize,
    error_rows: usize,
    preview: &[serde_json::Value],
) -> String {
    serde_json::to_string(&serde_json::json!({
        "valid": error_rows == 0 && total > 0,
        "format": format,
        "total_rows": total,
        "json_rows": json_rows,
        "csv_rows": csv_rows,
        "error_rows": error_rows,
        "preview": preview,
    }))
    .unwrap_or_else(|_| r#"{"valid":false,"format":"UNKNOWN","total_rows":0,"json_rows":0,"csv_rows":0,"error_rows":0,"preview":[]}"#.to_string())
}

// ---------------------------------------------------------------------------
// Score histogram and distribution statistics
//
// Parses all score values from any supported format (JSON, CSV, TSV, TOML, text)
// and computes:
//   buckets: [{min, max, count}, ...]
//   stats:   {min, max, mean, std, count}
// ---------------------------------------------------------------------------
#[wasm_bindgen]
pub fn score_histogram(data: &[u8], bucket_count: u32) -> String {
    let buckets_n = bucket_count.max(1) as usize;
    let mut scores: Vec<f64> = Vec::new();

    // JSON array
    let first_nonws = data.iter().copied().find(|b| !b.is_ascii_whitespace());
    if first_nonws == Some(b'[') {
        if let Ok(serde_json::Value::Array(arr)) = serde_json::from_slice::<serde_json::Value>(data) {
            for val in &arr {
                let s = wasm_extract_score(val);
                if s.is_finite() {
                    scores.push(s);
                }
            }
            return build_histogram(scores, buckets_n);
        }
    }

    // TOML
    if let Ok(s) = std::str::from_utf8(data) {
        if looks_like_toml_wasm(data) {
            if let Ok(tval) = toml::from_str::<toml::Value>(s) {
                if let Ok(json_str) = serde_json::to_string(&tval) {
                    if let Ok(jval) = serde_json::from_str::<serde_json::Value>(&json_str) {
                        collect_scores_from_json_value(&jval, &mut scores);
                        return build_histogram(scores, buckets_n);
                    }
                }
            }
        }
    }

    // Line-by-line
    for raw_line in data.split(|&b| b == b'\n') {
        let trimmed: Vec<u8> = raw_line
            .iter()
            .copied()
            .skip_while(|b| b.is_ascii_whitespace())
            .collect();
        if trimmed.is_empty() {
            continue;
        }

        let score = if trimmed.first() == Some(&b'{') {
            serde_json::from_slice::<serde_json::Value>(&trimmed)
                .ok()
                .map(|v| wasm_extract_score(&v))
        } else if trimmed.contains(&b'\t') {
            let s = String::from_utf8_lossy(&trimmed);
            let parts: Vec<&str> = s.splitn(8, '\t').collect();
            Some(extract_delimited_score(&parts))
        } else if trimmed.contains(&b',') {
            let s = String::from_utf8_lossy(&trimmed);
            let parts: Vec<&str> = s.splitn(8, ',').collect();
            Some(extract_delimited_score(&parts))
        } else {
            None
        };

        if let Some(s) = score {
            if s.is_finite() {
                scores.push(s);
            }
        }
    }

    build_histogram(scores, buckets_n)
}

fn collect_scores_from_json_value(val: &serde_json::Value, scores: &mut Vec<f64>) {
    match val {
        serde_json::Value::Array(arr) => {
            for item in arr {
                let s = wasm_extract_score(item);
                if s.is_finite() {
                    scores.push(s);
                }
            }
        }
        serde_json::Value::Object(_) => {
            let s = wasm_extract_score(val);
            if s.is_finite() {
                scores.push(s);
            }
        }
        serde_json::Value::Number(n) => {
            if let Some(f) = n.as_f64() {
                if f.is_finite() {
                    scores.push(f);
                }
            }
        }
        _ => {}
    }
}

fn build_histogram(scores: Vec<f64>, buckets_n: usize) -> String {
    if scores.is_empty() {
        return r#"{"buckets":[],"stats":{"min":0.0,"max":0.0,"mean":0.0,"std":0.0,"count":0}}"#
            .to_string();
    }

    let min = scores.iter().cloned().fold(f64::INFINITY, f64::min);
    let max = scores.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let mean = scores.iter().sum::<f64>() / scores.len() as f64;
    let variance =
        scores.iter().map(|&s| (s - mean).powi(2)).sum::<f64>() / scores.len() as f64;
    let std = variance.sqrt();

    let range = (max - min).max(1e-10);
    let mut counts = vec![0u32; buckets_n];
    for &s in &scores {
        let idx = ((s - min) / range * buckets_n as f64) as usize;
        counts[idx.min(buckets_n - 1)] += 1;
    }

    let bucket_data: Vec<serde_json::Value> = (0..buckets_n)
        .map(|i| {
            let lo = min + range * i as f64 / buckets_n as f64;
            let hi = min + range * (i + 1) as f64 / buckets_n as f64;
            serde_json::json!({ "min": lo, "max": hi, "count": counts[i] })
        })
        .collect();

    serde_json::to_string(&serde_json::json!({
        "buckets": bucket_data,
        "stats": {
            "min": min,
            "max": max,
            "mean": mean,
            "std": std,
            "count": scores.len(),
        }
    }))
    .unwrap_or_else(|_| r#"{"error":"serialization failed"}"#.to_string())
}

// ---------------------------------------------------------------------------
// Letter colors — return the 22 hex strings as a JSON array string.
// ---------------------------------------------------------------------------
#[wasm_bindgen]
pub fn letter_colors_hex() -> String {
    let colors = [
        "#E63946", "#F4A261", "#E9C46A", "#2A9D8F", "#264653", "#457B9D",
        "#A8DADC", "#48CAE4", "#023E8A", "#7B2D8B", "#C77DFF", "#FF6B6B",
        "#FFD93D", "#6BCB77", "#4D96FF", "#FF9F1C", "#FFBF69", "#CBF3F0",
        "#2EC4B6", "#E76F51", "#F1FAEE", "#A8C5A0",
    ];
    serde_json::to_string(&colors).unwrap_or_else(|_| "[]".to_string())
}

// ---------------------------------------------------------------------------
// Hebrew letter metadata — names, literals, pictorials, numerics as JSON
// ---------------------------------------------------------------------------
#[wasm_bindgen]
pub fn hebrew_alphabet_json() -> String {
    serde_json::to_string(&[
        ["א","Aleph","ox","strength/leader","1"],
        ["ב","Bet","house","household","2"],
        ["ג","Gimel","camel","movement/provision","3"],
        ["ד","Dalet","door","entry/path","4"],
        ["ה","He","window","revelation/breath","5"],
        ["ו","Vav","hook","connection","6"],
        ["ז","Zayin","weapon","cut/separate","7"],
        ["ח","Chet","fence","boundary/life","8"],
        ["ט","Tet","basket","contain/coil","9"],
        ["י","Yod","hand","work/act","10"],
        ["כ","Kaf","palm","cover/open","20"],
        ["ל","Lamed","staff","teach/direct","30"],
        ["מ","Mem","water","flow/chaos","40"],
        ["נ","Nun","seed/fish","continuity","50"],
        ["ס","Samekh","support","uphold/protect","60"],
        ["ע","Ayin","eye","watch/know","70"],
        ["פ","Pe","mouth","speak/declare","80"],
        ["צ","Tsadi","hook/plant","righteous trail","90"],
        ["ק","Qof","back of head","horizon/cycle","100"],
        ["ר","Resh","head","first/chief","200"],
        ["ש","Shin","tooth","consume/transform","300"],
        ["ת","Tav","mark/sign","covenant/seal","400"],
    ])
    .unwrap_or_else(|_| "[]".to_string())
}
