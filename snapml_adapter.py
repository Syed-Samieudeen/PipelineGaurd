"""Optional IBM Snap ML accelerator for failure classification.

snapml (and any trained Snap ML model) is OPTIONAL. When unavailable this module
returns None and guard.py falls back to the existing sklearn classifier
(classifier.py), which is the documented default behaviour.

Kept deliberately dependency-free: no import of snapml happens unless the package
is actually installed, so the project runs on any architecture (incl. s390x)
without snapml being present.
"""
from pathlib import Path

SNAPML_MODEL = Path(__file__).parent / "models" / "snapml_clf.joblib"


def predict(error_text, features, input_path=None, execution_time_ms=0.0, **kwargs):
    """Return (label, confidence) when a Snap ML model is available, else None.

    guard.py treats a None return as "use the existing classifier".
    """
    try:
        import snapml  # noqa: F401
    except ImportError:
        return None
    if not SNAPML_MODEL.exists():
        return None
    try:
        import joblib
        import pandas as pd
        from datafeatures import FEATURES

        pipe = joblib.load(SNAPML_MODEL)
        row = [{"error_text": error_text,
                **{k: features.get(k, 0.0) for k in FEATURES}}]
        probs = pipe.predict_proba(pd.DataFrame(row))[0]
        i = probs.argmax()
        return pipe.classes_[i], float(probs[i])
    except Exception:
        # Any failure to use the optional accelerator -> existing classifier.
        return None
