python3 -m unittest discover -s tools/lexical_quality -p 'test_*.py' -v
python3 -m compileall -q tools/lexical_quality
git diff --check
