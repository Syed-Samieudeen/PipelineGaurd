"""Predictive layer: Random Forest on (error-text TF-IDF + data-profile features). Trained on REAL failures from dataset.py."""
import json, joblib
from pathlib import Path
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.pipeline import Pipeline
import dataset
from datafeatures import FEATURES

DIR = Path(__file__).parent / "models"; MODEL = DIR / "failure_clf.joblib"; METRICS = DIR / "metrics.json"; DATA = DIR / "failures.csv"

def _pipe(use_features=True):
    parts = [("t", TfidfVectorizer(ngram_range=(1, 2), min_df=2), "error_text")]
    if use_features: parts.append(("n", "passthrough", FEATURES))
    return Pipeline([("pre", ColumnTransformer(parts)), ("rf", RandomForestClassifier(n_estimators=200, random_state=0, class_weight="balanced"))])

def train(n=600):
    DIR.mkdir(exist_ok=True); df = dataset.generate(n); df.to_csv(DATA, index=False)
    X, y = df[["error_text"] + FEATURES], df["label"]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, stratify=y, random_state=0)
    full = _pipe().fit(Xtr, ytr); pred = full.predict(Xte)
    text_only = _pipe(False).fit(Xtr, ytr); pred_t = text_only.predict(Xte)
    labels = sorted(y.unique())
    m = {"n_samples": len(df), "class_counts": y.value_counts().to_dict(),
         "test_accuracy": round(accuracy_score(yte, pred), 4), "test_macro_f1": round(f1_score(yte, pred, average="macro"), 4),
         "cv5_accuracy": round(cross_val_score(_pipe(), X, y, cv=5).mean(), 4),
         "text_only_accuracy": round(accuracy_score(yte, pred_t), 4),
         "labels": labels, "confusion_matrix": confusion_matrix(yte, pred, labels=labels).tolist(),
         "per_class": classification_report(yte, pred, output_dict=True, zero_division=0)}
    METRICS.write_text(json.dumps(m, indent=2)); _pipe().fit(X, y); joblib.dump(_pipe().fit(X, y), MODEL); return m

def predict(error_text, features):
    if not MODEL.exists(): train()
    pipe = joblib.load(MODEL)
    probs = pipe.predict_proba(pd.DataFrame([{"error_text": error_text, **{k: features.get(k, 0.0) for k in FEATURES}}]))[0]
    i = probs.argmax(); return pipe.classes_[i], float(probs[i])

if __name__ == "__main__": print(json.dumps(train(), indent=2))
