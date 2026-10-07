"""AWS Lambda entry point: wraps the FastAPI app with Mangum (Function URL / API Gateway)."""
from mangum import Mangum

from .main import app

handler = Mangum(app, lifespan="off")
