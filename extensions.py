"""
extensions.py
Shared application extensions — initialised once, imported everywhere.

MongoClient construction is intentionally lazy (PyMongo does not connect
until the first operation).  Index creation is deferred to init_db(),
which is called explicitly from app.py after the Flask app is created.
This means import failures are impossible and startup errors are surfaced
with a clear message rather than a cryptic traceback.
"""
import logging
import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

logger = logging.getLogger(__name__)

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
_client   = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db        = _client["civicdb"]

# Collections — assigned at module level so blueprints can import them
# immediately.  No network I/O happens here.
users_col       = db["users"]
complaints_col  = db["complaints"]
otp_col         = db["otp_verifications"]
reset_col       = db["password_resets"]
activity_col    = db["complaint_activity"]
rate_limits_col = db["rate_limits"]


def init_db() -> None:
    """
    Verify the MongoDB connection and create all indexes.
    Call this once from app.py at startup — never at import time.

    Raises RuntimeError with a human-readable message if MongoDB is
    unreachable so the developer gets a clear error instead of a
    confusing traceback buried in PyMongo internals.
    """
    try:
        # ping is the lightest possible command — confirms connectivity
        _client.admin.command("ping")
        logger.info("MongoDB connected → %s", MONGO_URI)
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        raise RuntimeError(
            f"Cannot connect to MongoDB at {MONGO_URI!r}. "
            "Check that MongoDB is running and MONGO_URI is set correctly in .env.\n"
            f"Original error: {exc}"
        ) from exc

    # Indexes — all idempotent, safe to call on every startup
    users_col.create_index("email", unique=True)
    otp_col.create_index("expires_at", expireAfterSeconds=0)
    reset_col.create_index("expires_at", expireAfterSeconds=0)
    activity_col.create_index("complaint_id")
    activity_col.create_index([("timestamp", -1)])
    complaints_col.create_index([("created_at", -1)])
    complaints_col.create_index("user_id")
    complaints_col.create_index("department")
    complaints_col.create_index("status")
    rate_limits_col.create_index("expires_at", expireAfterSeconds=0)
    rate_limits_col.create_index([("action", 1), ("ip", 1)])
    logger.info("MongoDB indexes verified.")

