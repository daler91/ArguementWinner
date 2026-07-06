from __future__ import annotations

from argumentwinner.adapters.discord.sending import split_message, truncate_at_boundary


def test_short_text_untouched():
    assert truncate_at_boundary("fine as is") == "fine as is"
    assert split_message("fine as is") == ["fine as is"]


def test_truncates_at_sentence_boundary_under_limit():
    text = "First sentence here. Second sentence follows. " + "x" * 2000
    cut = truncate_at_boundary(text, 100)
    assert cut.endswith(".")
    assert len(cut) <= 100


def test_truncates_at_word_boundary_when_no_sentence_break():
    text = "word " * 500
    cut = truncate_at_boundary(text, 100)
    assert len(cut) <= 100
    assert not cut.rstrip("…").endswith("wor")  # no mid-word cut


def test_hard_slice_backstop_for_unbroken_text():
    cut = truncate_at_boundary("y" * 5000, 100)
    assert len(cut) <= 100


def test_split_chunks_all_fit_and_lose_nothing_material():
    sentences = " ".join(f"Sentence number {i} makes a point." for i in range(200))
    chunks = split_message(sentences, 500)
    assert all(len(c) <= 500 for c in chunks)
    assert len(chunks) > 1
    rejoined = " ".join(chunks)
    assert "Sentence number 0" in rejoined
    assert "Sentence number 199" in rejoined


def test_split_loses_zero_characters_on_the_hard_slice_path():
    """The '…' continuation marker is display-only: reassembling the chunks
    (markers stripped) must reproduce the original text exactly."""
    text = "y" * 5000
    chunks = split_message(text, 100)
    assert "".join(c.rstrip("…") for c in chunks) == text


def test_split_loses_zero_words_on_the_word_boundary_path():
    words = [f"w{i}" for i in range(1000)]
    chunks = split_message(" ".join(words), 80)
    reassembled = " ".join(c.rstrip("…").strip() for c in chunks).split()
    assert reassembled == words
