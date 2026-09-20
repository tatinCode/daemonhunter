import argparse
import getpass
import sqlite3
from datetime import datetime
from pathlib import Path
from secrets import token_urlsafe

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.engine import make_url

from daemonhunter.auth import hash_password
from daemonhunter.config import DATABASE_URL
from daemonhunter.database import SessionFactory, engine
from daemonhunter.models import User


def prompt_for_password() -> str:


