"""User feedback capture (thumbs up/down + comments) for answer quality."""

from src.feedback.store import (
    FeedbackRecord,
    list_feedback,
    save_feedback,
    summarize_feedback,
)

__all__ = ["FeedbackRecord", "list_feedback", "save_feedback", "summarize_feedback"]
