import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
BQ_PROJECT = os.environ["BQ_PROJECT"]
BQ_DATASET = "DA_aggregate_published"
