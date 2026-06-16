if [ -f ".venv/bin/activate" ]; then
    . .venv/bin/activate
fi

if [ -f "update.py" ]; then
    python3 update.py || true
fi

python3 -m bot
