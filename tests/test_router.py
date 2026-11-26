"""Which specialist takes a turn (design of 2026-11-15): worked out from the message, with no model call."""
import pytest

from ledgersync.agent.router import BOOKKEEPER, LEAD, REPORTER, REVIEWER, TAX, route

CASES = [
    # (trigger, text, files with it, the specialist of the turn before) -> who takes it
    ("background", "Background review for 2 dates to settle. Check the VAT return and the dividend.", False, None, REVIEWER),
    ("chat", 'Answer to "Which account should the toll go to?": Travel', False, None, BOOKKEEPER),
    ("chat", "What VAT can I reclaim on these?", True, None, REVIEWER),            # files came with it
    ("chat", "What needs my attention?", False, None, REPORTER),
    ("chat", "Show the trial balance", False, None, REPORTER),
    ("chat", "Review the documents I'm adding", False, None, REVIEWER),
    ("chat", "Put the toll to Travel", False, None, BOOKKEEPER),
    ("chat", "Reclaim the VAT on the hotel", False, None, BOOKKEEPER),             # an instruction, though it says VAT
    ("chat", "Can you move the Shell receipt to motor expenses?", False, None, BOOKKEEPER),
    ("chat", "please change the date of the taxi to 14 Oct", False, None, BOOKKEEPER),
    ("chat", "That warning is fine", False, None, BOOKKEEPER),
    ("chat", "I have the VAT invoice for the laptop", False, None, BOOKKEEPER),
    ("chat", "Can I reclaim VAT on a van?", False, None, TAX),
    ("chat", "What goes in box 6?", False, None, TAX),
    ("chat", "Can a dividend be paid?", False, None, TAX),
    ("chat", "How much corporation tax should I allow for?", False, None, TAX),
    ("chat", "Is there an s455 charge on the director's loan?", False, None, TAX),
    ("chat", "What has changed since yesterday?", False, None, REPORTER),
    ("chat", "How much did we spend on travel?", False, None, REPORTER),
    ("chat", "Is the trial balance balanced?", False, None, REPORTER),
    ("chat", "Give me a summary of the year", False, None, REPORTER),
    ("chat", "Who still owes us money?", False, None, REPORTER),
    ("chat", "Check the VAT on the Booker invoice", False, None, REVIEWER),        # not a question: a check of evidence
    ("chat", "Go through the duplicates", False, None, REVIEWER),
    ("chat", "Sort out the dates", False, None, REVIEWER),
    ("chat", "Why is the bank £499 out?", False, None, LEAD),                      # no rule places it
    ("chat", "Hello", False, None, LEAD),
    ("chat", "yes", False, BOOKKEEPER, BOOKKEEPER),                                # a follow-up stays where it was
    ("chat", "Travel", False, BOOKKEEPER, BOOKKEEPER),
    ("chat", "Continue", False, REVIEWER, REVIEWER),
    ("chat", "yes", False, None, LEAD),
    ("chat", "  WHAT   needs my\nattention?  ", False, None, REPORTER),             # case and spacing don't matter
    ("chat", "", False, None, LEAD),
]


@pytest.mark.parametrize("trigger, text, has_files, previous, who", CASES)
def test_each_message_goes_to_its_specialist(trigger, text, has_files, previous, who):
    assert route(trigger, text, has_files, previous) == who


def test_a_word_inside_another_word_places_nothing():
    assert route("chat", "The taxi was to the station") == LEAD          # "tax" in taxi
    assert route("chat", "Booking confirmed for the trip") == LEAD       # "book" in booking
