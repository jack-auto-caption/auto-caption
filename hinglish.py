"""
Devanagari -> Hinglish (Roman Hindi) transliteration.

Readable everyday Hinglish, not academic transliteration:
  सरकारी नौकरी की लाइन -> sarkari naukri ki lain
  देश सेवा -> desh seva | नहीं है -> nahin hai | लगता है -> lagta hai

Rules: inherent 'a' is dropped at word end (desh, not desha) and in
medial syllables before a matra syllable (lagta, naukri) — close to how
Hindi is actually spoken. Non-Devanagari text passes through unchanged.
"""

_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}
_NUKTA = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "फ": "f", "ड": "d", "ढ": "dh"}
_VOWELS = {  # independent vowels
    "अ": "a", "आ": "aa", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}
_MATRAS = {
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u",
    "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
}
_DIGITS = {chr(0x966 + i): str(i) for i in range(10)}
_HALANT = "्"
_NUKTA_CH = "़"
_MERGES = {("क", "ष"): "ksh", ("त", "र"): "tr", ("ज", "ञ"): "gy"}


def _parse(word):
    """Split a Devanagari word into syllables: {base, vowel, src, nasal}."""
    syls = []
    i, n = 0, len(word)
    while i < n:
        c = word[i]
        if c in _VOWELS:
            syls.append({"base": "", "vowel": _VOWELS[c], "src": "indep", "nasal": ""})
            i += 1
        elif c in _CONS:
            j = i + 1
            base = _CONS[c]
            if j < n and word[j] == _NUKTA_CH:
                base = _NUKTA.get(c, base)
                j += 1
            # conjunct merge: क+्+ष = ksh, त+्+र = tr, ज+्+ञ = gy
            if j + 1 < n and word[j] == _HALANT and (c, word[j + 1]) in _MERGES:
                base = _MERGES[(c, word[j + 1])]
                j += 2  # skip halant + second consonant
                if j < n and word[j] == _NUKTA_CH:
                    j += 1
            if j < n and word[j] == _HALANT:
                syls.append({"base": base, "vowel": "", "src": "none", "nasal": ""})
                i = j + 1
            elif j < n and word[j] in _MATRAS:
                syls.append({"base": base, "vowel": _MATRAS[word[j]], "src": "matra", "nasal": ""})
                i = j + 1
            else:
                syls.append({"base": base, "vowel": "a", "src": "inherent", "nasal": ""})
                i = j
        elif c in ("ं", "ँ"):
            if syls:
                syls[-1]["nasal"] = "n"
            i += 1
        elif c == "ः":
            if syls:
                syls[-1]["nasal"] = "h"
            i += 1
        elif c in _DIGITS:
            syls.append({"base": _DIGITS[c], "vowel": "", "src": "none", "nasal": ""})
            i += 1
        else:  # punctuation / latin / anything else rides on the last syllable
            if syls:
                syls[-1]["nasal"] += c
            else:
                syls.append({"base": c, "vowel": "", "src": "none", "nasal": ""})
            i += 1
    return syls


def to_hinglish(word):
    if not any("ऀ" <= ch <= "ॿ" for ch in word):
        return word
    syls = _parse(word)
    out = []
    for idx, s in enumerate(syls):
        v = s["vowel"]
        if s["src"] == "inherent":
            is_last = idx == len(syls) - 1
            if is_last and s["base"] != "y":
                v = ""  # desh, ghar, nam — final schwa drops
            elif (not is_last and idx > 0
                    and syls[idx - 1]["src"] != "none"
                    and syls[idx - 1]["nasal"] == ""
                    and syls[idx + 1]["src"] == "matra"):
                v = ""  # lagta, naukri, kahani — medial schwa drops (not after clusters: zindagi)
        out.append(s["base"] + v + s["nasal"])
    return "".join(out)


def hinglish_text(text):
    return " ".join(to_hinglish(w) for w in text.split(" "))
