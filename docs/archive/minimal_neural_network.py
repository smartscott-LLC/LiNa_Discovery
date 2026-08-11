"""
Minimal neural network class for experimentation with combinatorial structures.
This class is designed to be flexible for mapping custom architectures.

Used by EmbodiedSelfModel: a small online learner that maps a 14D decision
vector through the dimension-level topology derived from the polytope's
combinatorial structure. It is not a pretrained classifier — it adapts
incrementally from confirmed encoder corrections.
"""

import numpy as np


class MinimalNeuralNetwork:
    def __init__(self, structure):
        self.structure = structure
        self.weights = self.initialize_weights()

    def initialize_weights(self):
        # Weights are derived from the structure's node count. The network
        # starts small and neutral (amplitude 0.05); it only becomes
        # meaningful after adapt() updates from confirmed corrections.
        num_nodes = len(self.structure.get('nodes', [])) or 10
        weights = np.random.randn(num_nodes, num_nodes) * 0.05
        return weights

    def forward(self, x):
        # Single linear layer: the self-state modulation is squashed and
        # blended (at 15%) by the caller, so the network influences but
        # never dominates the polytope evaluation.
        return np.dot(x, self.weights)

    def adapt(self, x, target, learning_rate=0.01):
        """Single-step online update toward a target vector."""
        x_vec = np.asarray(x, dtype=float).reshape(-1)
        target_vec = np.asarray(target, dtype=float).reshape(-1)

        pred = np.asarray(self.forward(x_vec.reshape(1, -1)), dtype=float).reshape(-1)
        if pred.shape[0] != target_vec.shape[0]:
            pred = np.resize(pred, target_vec.shape[0])

        error = target_vec - pred
        if x_vec.shape[0] != self.weights.shape[0]:
            x_vec = np.resize(x_vec, self.weights.shape[0])
        if error.shape[0] != self.weights.shape[1]:
            error = np.resize(error, self.weights.shape[1])

        self.weights += learning_rate * np.outer(x_vec, error)
        self.weights = np.clip(self.weights, -3.0, 3.0)

    def explore(self):
        """Small exploratory perturbation of the weights, bounded and neutral."""
        noise = np.random.randn(*self.weights.shape) * 0.01
        self.weights = np.clip(self.weights + noise, -3.0, 3.0)

if __name__ == "__main__":
    # Example usage
    structure = {'nodes': list(range(10)), 'edges': []}
    nn = MinimalNeuralNetwork(structure)
    x = np.random.randn(1, 10)
    output = nn.forward(x)
    print("Output:", output)
    nn.explore()
