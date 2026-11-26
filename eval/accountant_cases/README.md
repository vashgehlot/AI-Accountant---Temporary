# Accountant cases: do the rules ask what an accountant would, for any kind of business?

Each `<case>.json` is one made-up but realistic client, a different kind of business from the clients whose
documents the app was built on, with its rows as the reader would give them. Each row may say what an accountant
would expect of it:

- `asks`: warnings that must be on the row (a question an accountant would put).
- `never`: codes that must not be on the row (a question no accountant would put, or a note that doesn't belong).
- `account`: the account it must end up on.

`tests/test_accountant_cases.py` loads every case into a fresh database and checks each expectation against the
books as the page shows them. The expectations are an accountant's, written before the rules were run: a failing
case is a rule that doesn't generalise, not a case to change.

Fields of a row are `Transaction` inputs. Every client has its first year to 31 Mar 2027.
