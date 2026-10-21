1. **Analyze existing code**
   - The initial code for `tools/lexical_quality` has been mostly provided, and passes structural and unit tests.
   - However, the `LexicalValidator` uses an unbounded standard `set` for `seen_ids`. This violates the strict "bounded memory requirements" constraint over massive data streams.
2. **Apply memory limits using OrderedDict**
   - According to internal guidelines, we must use an `OrderedDict` acting as an LRU-like set (evicting the oldest items) for duplicate detection in a bounded memory space.
   - We will update `LexicalValidator.__init__` to initialize `self.seen_ids = collections.OrderedDict()` and set a maximum capacity (e.g., 100,000 items).
   - In `validate_entry`, we will insert into the `OrderedDict` and `popitem(last=False)` if it exceeds the limit.
3. **Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.**
   - Run tests using the `run_tests.sh` script.
   - Verify code using `git diff`.
4. **Submit PR**
   - Commit and submit the code with the required `[skip ci]` message format.
