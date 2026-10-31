"""Kalibracja na predykcjach out-of-fold, osobno per rynek.

Dla 1X2 (3 klasy): skalowanie temperatury, "vector scaling" (Platt wieloklasowy na log p)
albo izotoniczna jeden-przeciw-reszcie z renormalizacja. Dla rynkow binarnych: Platt albo izotoniczna.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from sklearn.isotonic import IsotonicRegression

EPS = 1e-9


def _softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def _nll(P, y):
    return -np.mean(np.log(np.clip(P[np.arange(len(y)), y], EPS, 1)))


class Multiclass:
    def __init__(self, method: str = "vector"):
        self.method = method
        self.theta = None
        self.iso = None

    def fit(self, P: np.ndarray, y: np.ndarray) -> "Multiclass":
        L = np.log(np.clip(P, EPS, 1))
        k = P.shape[1]
        if self.method == "temperature":
            f = lambda t: _nll(_softmax(L / max(t[0], 0.05)), y)
            self.theta = minimize(f, [1.0], method="Nelder-Mead").x
        elif self.method == "vector":
            # p_k ~ exp(a_k * log p_k + b_k), b_0 = 0 (identyfikowalnosc)
            def f(t):
                a, b = t[:k], np.r_[0.0, t[k:]]
                return _nll(_softmax(L * a + b), y) + 1e-4 * np.sum((a - 1) ** 2)
            self.theta = minimize(f, np.r_[np.ones(k), np.zeros(k - 1)], method="L-BFGS-B").x
        elif self.method == "isotonic":
            self.iso = [IsotonicRegression(out_of_bounds="clip", y_min=EPS, y_max=1).fit(P[:, j], y == j)
                        for j in range(k)]
        elif self.method != "none":
            raise ValueError(self.method)
        return self

    def transform(self, P: np.ndarray) -> np.ndarray:
        L = np.log(np.clip(P, EPS, 1))
        k = P.shape[1]
        if self.method == "temperature":
            return _softmax(L / max(self.theta[0], 0.05))
        if self.method == "vector":
            a, b = self.theta[:k], np.r_[0.0, self.theta[k:]]
            return _softmax(L * a + b)
        if self.method == "isotonic":
            Q = np.column_stack([iso.predict(P[:, j]) for j, iso in enumerate(self.iso)])
            Q = np.clip(Q, EPS, None)
            return Q / Q.sum(axis=1, keepdims=True)
        return P


class Binary:
    def __init__(self, method: str = "platt"):
        self.method = method
        self.theta = None
        self.iso = None

    def fit(self, p: np.ndarray, y: np.ndarray) -> "Binary":
        if self.method == "platt":
            x = np.log(np.clip(p, EPS, 1)) - np.log(np.clip(1 - p, EPS, 1))

            def f(t):
                q = 1 / (1 + np.exp(-(t[0] * x + t[1])))
                q = np.clip(q, EPS, 1 - EPS)
                return -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))
            self.theta = minimize(f, [1.0, 0.0], method="Nelder-Mead").x
        elif self.method == "isotonic":
            self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(p, y)
        elif self.method != "none":
            raise ValueError(self.method)
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        if self.method == "platt":
            x = np.log(np.clip(p, EPS, 1)) - np.log(np.clip(1 - p, EPS, 1))
            return 1 / (1 + np.exp(-(self.theta[0] * x + self.theta[1])))
        if self.method == "isotonic":
            return self.iso.predict(p)
        return p
