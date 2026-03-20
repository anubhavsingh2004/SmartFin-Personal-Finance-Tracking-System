"""Expense categorization model using Naive Bayes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

from utils.database import get_db_connection


BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "models" / "expense_classifier.joblib"
SEED_DATA_PATH = BASE_DIR / "data" / "seed_transactions.csv"


class ExpenseCategorizer:
    """Wrap model loading, training, prediction, and retraining."""

    def __init__(self) -> None:
        self.pipeline: Pipeline | None = None
        self._load_or_train()

    def _is_model_stale(self) -> bool:
        """Return True when the seed dataset changed after the model was saved."""
        if not MODEL_PATH.exists():
            return True

        try:
            model_mtime = MODEL_PATH.stat().st_mtime
            seed_mtime = SEED_DATA_PATH.stat().st_mtime
        except OSError:
            return True

        return seed_mtime > model_mtime

    def _load_or_train(self) -> None:
        if not self._is_model_stale():
            try:
                self.pipeline = joblib.load(MODEL_PATH)
                return
            except Exception:
                # If the serialized model is corrupted or incompatible, retrain.
                self.pipeline = None

        self.train_model()

    def _build_training_frame(self) -> pd.DataFrame:
        seed_frame = pd.read_csv(SEED_DATA_PATH)

        connection = get_db_connection()
        try:
            user_frame = pd.read_sql_query(
                "SELECT description, category FROM transactions WHERE type = 'Expense'",
                connection,
            )
        except (sqlite3.OperationalError, pd.errors.DatabaseError):
            user_frame = pd.DataFrame(columns=["description", "category"])
        finally:
            connection.close()

        if not user_frame.empty:
            training_frame = pd.concat([seed_frame, user_frame], ignore_index=True)
        else:
            training_frame = seed_frame.copy()

        training_frame = training_frame.dropna().drop_duplicates()
        training_frame["description"] = training_frame["description"].astype(str)
        training_frame["category"] = training_frame["category"].astype(str)
        return training_frame

    def train_model(self) -> None:
        training_frame = self._build_training_frame()
        pipeline = Pipeline(
            [
                ("vectorizer", TfidfVectorizer(stop_words="english")),
                ("classifier", MultinomialNB()),
            ]
        )
        pipeline.fit(training_frame["description"], training_frame["category"])
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(pipeline, MODEL_PATH)
        self.pipeline = pipeline

    def predict_category(self, description: str) -> str:
        if not description.strip():
            return "Other"

        if self.pipeline is None:
            self.train_model()

        prediction = self.pipeline.predict([description])[0]
        return str(prediction)

    def retrain_with_latest_data(self) -> None:
        self.train_model()


expense_categorizer = ExpenseCategorizer()
