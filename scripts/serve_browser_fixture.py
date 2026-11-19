"""Loopback-only mock browser fixture with a public, throwaway test password."""
import os
import tempfile
from pathlib import Path

import uvicorn
from vaanibench.hosted import Settings,create_app
from vaanibench.hosted_auth import password_hash

if __name__=='__main__':
    for key in ['OPENAI_API_KEY','GROQ_API_KEY','VAANIBENCH_DATABASE_URL','VAANIBENCH_OTLP_ENABLED']:
        os.environ.pop(key,None)
    base=Path('artifacts/browser-fixture');base.mkdir(parents=True,exist_ok=True)
    settings=Settings(root=Path.cwd(),state_dir=Path(tempfile.mkdtemp(prefix='session-',dir=base)),origin='http://127.0.0.1:8771',
        owner_password_hash=password_hash('temporary browser-only test password'),mock_pace_seconds=.15)
    uvicorn.run(create_app(settings),host='127.0.0.1',port=8771,workers=1,access_log=False)
