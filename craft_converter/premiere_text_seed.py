"""Neutral native Premiere Type-tool text graph layout.

Adapted from `feature_text_point.prproj` in Tesseract-Converter:
https://github.com/mirage-hq/Tesseract-Converter/blob/main/crates/premiere_file/tests/fixtures/feature_text_point.prproj
Source (compressed) SHA-256: 47ac41b7f2481c5b034d1adecb3423b61846ef493fb46fef94f8bcef07a88ddc
Only the 34 objects reachable from the text timeline item are retained;
project metadata and unused fixture objects are removed. Source Text and
identities are replaced when writing an FC project. The upstream work is MIT
licensed; notice preserved below.

MIT License

Copyright (c) tesseract-conv contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import base64
import gzip

_SEED_GZIP_BASE64 = (
    "H4sIAAAAAAACA+1bXXPbthJ9bn6Fhi95MSx8kQA8sjqS7SRu68SOneS2byAA2mxkSkNRSdxO/vsFSIoiRVF2XbnNzVxlhiaAJYA9"
    "uzi7AJnBj19uJ71PJp3H0+TwOdqHz3smUVMdJ9eHzxdZBPjzH4fPBuepuY1Nao5lJnvvS3GPeMPB+1ib6dEknl2lUn08zcxt7034"
    "u1HZ6fGhhyBCxOsdTeR87sok4CGkMABYGAKowASISGkABY3CSEgEufBW/XNv+OyHHwbN3tdabfP0djZNTJK9+ZyYdNWOivaawLyc"
    "2lsT5XOj0Ov1i076zV6Kyg2D0mWnl5lMsyEc9IubwUmihz7kkGCY/wZ9VzPoV30UXV4uQqfO+kRQORE7j7qyedV5/MVMRvOZk5dZ"
    "PB2iPTTot2qd6JXV4EzOLk2WWQPOh396MyM/egcA7Xmlkb0D8tXOak3QPfwilbfmre1vCPfgHhLYXqxCg/6q4ZmdYNvgrrqpV2l7"
    "p1ZlewOVz7USQIdaA4qCAEgTMeDrkBkSYWw4rdk+WNl+DawgWIJ1JueZSWsi73IZTFgU+iYCRBMFKCQIcG4wgBphHgZESY2XXby2"
    "qg1fpnJ2E6tBPy+56jdpfH108zKdOQuvCk7/UlN33x7fKfqw4StcohAhRYgEIZQCUBr4QEpBQRhoCw0OMFdRDReEC2B+mV5fW9Od"
    "JtF0DR8hlsq5mc1bC6LA9DTR5suhZ1dA42nrvQ1XLFxjtNBxbvOjG5kkZvIynS5m8/Un0T2gruBy3VybcmIO4q4mB/iqzRXXZ/He"
    "zmCaXpo0lpP4D7v+6x6Yz6lCWhKEmeQKCF9TQP3AAMkiHyCGQhIJjCkOvDW4ChS2DeiEqjWxNjqsjS4I5Dq0boEphYBKFQIhQ2wn"
    "Q0IhqeHYqProqLYAVrVL0ns91WYD1Z2n05lJs9i0zW5bxyf7lsij+f7lXZLdmCxWZ0bHcv/YRHIxyU7nx/bxfLUPs3RhBv2/8EAx"
    "fn81gZJX3URL6psuUmXWnZVXFPxmkZ1P4yRbo9GqOhc6TYqCbVjeVj59ejwkylBGoQEhUhJQ5ftAYG6Zxg+pbfFZFJnCpFa47PDd"
    "3AwjOZkb16UrVM7f5LvK0DkGDW1KvnPKrPguoFpHjAIeSUsDAceAS8kBtEQora9xQeuxrlzW9b7Xg44NZElmI1TNtNCrwlfeVJTy"
    "ThqU6CMZIEMDoAJhSSawd6H0OWBBgKSPiYCBqdZ9bQ4VGcaJnBwvUhdpkiGCghEqUGkjWHJkQ6aCrtlbc24Op4dNrYKVSV8hSAyI"
    "iIOVCGSZMqSAKUU0tjmENXENVlIgVBjuMkuNvF2nrSoWnNm0J4pVPn8b1TPTO1mmQl4o59agXm9slUzvXsn5jTUL5TQMIQa+CH1A"
    "ZEABZAgCHGhW4IKUN/z06zgyyU8vjt6r4GT88ePI/i5Gh4cF1OtDFpE4nphzmd0MERKBzygW1EbhZaWTOL2dTcytNXj+pPVlam3B"
    "DZNAmyACFDMIRKANYAZzJsNQhDS0/r3+WJ40xNmkRtdFMR8kieIkzpZkUBXziKCyhZzkxtw4203tz5a+Va2khkGWpIkblB3YZYsE"
    "IEYFljShAtLGS8BDKmVIGJPSry+ichUVGYuDk9OA4dJHV7VOZps317z4gXmRW5zaqKu7mRkiSiwU1IZyty6XtTmi88ssnkyWgJal"
    "osWt4DhZTBfzq7gi4FZ1fT0eTSc2EM2kXVh/5g6aV1gGjizi3sGfnqqVXRT2Drzx1T6Dovf25bj3YjGZeF/38idLITdR7wB9Xa3n"
    "2hi52SezG1koaW1cFaoml46czt8lysYAGSelFhubCkc3E+16aD+zsakilcJx7MbEEXM7FVrysagTh10GLLKpp1barpDA10BYbgFM"
    "EmIZGRlGuNei1sGRnGWL1Jy5MIatPWvFZXhupjtVTbG2bo2lEPNimt7KzLoadgusUVexft1pmR/kflsumLrnFiPUdO5OQPJU+f8J"
    "yD+ZgDBEIA4CDVTIkU1AILQ5JrYXYhN/Ro2mTNcTkK2JRrUntflnnKztreq5pWUwm1ZwCSKfW9+29ARCLCRAkiEWcoOwwV5j354z"
    "YAHi2TSnugLwZl1N6o3lgDi7a4otK1u9VTO3WqK1Xutt7QHqrXh9oPVH1wBaU/CRTnr2236z330bzOJPZm1mDxF7aI/n0rpwviMb"
    "uvAp7NoX/gOGqD13v/vXjkG2nJF0bQxR4G84LJmXPtyYZc2bW/V5tc0I3I6uGrLJWX7NsTWCWloeB6ExNp/X2mZ7giJgNJGM2xRR"
    "+7Dm2MJrusWqhZUekSO2CYC8oVN5tjxzWJdELUnWIYlbkrxDkrQkRYckXZfksEPSb0miDsmgJYk7JFlLknRI8pYk7ZAULUm/C/mW"
    "kXinkVpW4l1WQi0z8S4zoZadeJedUMtQostQqGUp0WUp1DKV6DIVatlKdNkKtYwluoyFWtYSXdbCLWuJLmvhlrUEW1FPsYDLWGz3"
    "PTYMlzv543g+m8i7PPe6Ml8yGzxqNWXwnmfSZpN5zezOhfBaRZPKirPX8ty7YKzzNP5kk7D8EHz71lBRqAJieSsIcQC4wgpERkZA"
    "QxSWuwztDUfLbWDnMOW5WaZu8hmOTvZHx+OTXqHeqr7a4RYd5Dk5Ljm4VlXx8hoBtxOOwiDNZJrVeFkphAl1u3CEiOVlEgJpoG+z"
    "Ds50yJimAdqQTOeT7dWOBPNxjJ2Li6m4tG5ZfrY8Zf/Z3EV5igcEotRnAax+e/nBzR5c/SsP5Ktn2rEoH+NhKtfT58htRLEwIFCC"
    "Ahop6M4RfaCgH0gf2Z1oRLpUtn27aPR2Wmy8NwHg9nnpdJLbidSAqNe3EEOPQAzub4fLHS1/Nul4ukj0EBDMAj7o16qcxLvZbFl0"
    "AmzQr9X8LcT93SL+ysTXN1mXw8Gnhg9uQw4X24tdIUd3i9yHWGc3HcAh8T0BR56Y1xD/5ngNP7XK7JtTGT21ysE3pzJ8apX9b01l"
    "Xj/wkzSKsA4MYFJhQGnEgdA+BohpoaQPjU9xl8om0V1K00coDdBfCroIbuU/BFcn1TsiQc53BNzcKdYFHfkuoWM7gq5zmeF/NdqW"
    "GeCu0AqeGi30PaHl/30K37iTaPjUti0Ggk/D8Q3QyrfvDwMtP3PfClo9E1aSI00oAwSK0LqYxkAqxQBSPsMmCgUj9ZcetOZho0Td"
    "TNNePl6Hsz0qDz6AdWj2/D26LRRuUPdhrkN2tB8oj947EHhMbmtJeGfrDe2SyfGOINv1Pp99b9t8/tTZ+GOScfdm68kSU7gj13o1"
    "TeM/rKvISe9SyYnp0N//l5cl3WWGxcSOwNuGGP0fQuzeEMj4bkLg+XQedxGZ+9ruUbyE/QO47/8TMZDt6sj6KpXJPJqmt/cxeiP7"
    "3Hp0+62lVaM0vB/PevJOELH5uaYgENB9yy81CGEYAY4DrLRGMKKm/c3BxjfyW1/ID06OzvfLr2vm+ydfZjLRRpffIWxue7bhVfjq"
    "TXjJBcXHIMWblO1GFQ/Nle+x6XI1bbDtmiUryVYf7+Vkcd93idJgRWCIAA2VXfCS+ICHWgEiuAmphIIHoTe8GJ2Mit/45Ozu9O3x"
    "snQ9+tl9oWj/jkYvL4rKF3T00lWOPo/+7u/F9UOkSqGxGo0/j01V/Ta/Knd5vay7GL/r29+Hc3tBf9iLuHbl0UXxpaX9neV3//lp"
    "9uuHz9nFrZj/doLeFQ+fVO1H+d8L9/e0LNvmi+pWvco/3Ry9vh79mutRn+74odrn+J26cV5fl7flJJfWuHY3R+Nj4fTp/+4u3F3G"
    "uUguerjmLrlT5It78youSLT2X3iG/wUsNJZn+DMAAA=="
)


def load_text_seed_xml() -> bytes:
    """Return the small, public, neutral graphic layout for cloning."""
    return gzip.decompress(base64.b64decode(_SEED_GZIP_BASE64))
