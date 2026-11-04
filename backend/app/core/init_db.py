"""Initialize the local schema: python -m app.core.init_db.

create_all supports a fresh database, not migrations of existing tables.
"""
from app.core.database import Base, get_engine
from app.models import zcash  # noqa: F401: additive testnet tables
from app.models import spending  # noqa: F401: register tables
from app.models import bitrefill  # noqa: F401: register additive integration tables


def main():
    Base.metadata.create_all(get_engine())


if __name__ == "__main__":
    main()
