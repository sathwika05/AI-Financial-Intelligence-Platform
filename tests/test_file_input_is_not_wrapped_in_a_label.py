"""
A file input must not be nested inside its <label>.

Every other field on the admin screens wraps its control in a label, which
is correct for text inputs and selects: clicking the label focuses the
control, and clicking the control does nothing extra.

A file input is different. Clicking it opens the picker AND bubbles to the
label, whose activation behaviour is to click the labelled control -- which
asks for the picker a second time. The browser cancels the earlier dialog
each time, so the picker flickers or never appears at all, and the Choose
File button looks dead.

Measured on the deployed build before the fix: one interaction with the
upload field produced 22 file-chooser events. The button had never worked
in a real browser.

The fix is `htmlFor` plus an `id`, which gives the same click-to-focus
behaviour and the same accessible name without the second activation.

Read from the source: there is no frontend test runner, and this is a
structural rule about one element rather than behaviour worth booting a
browser for.
"""
import re
from pathlib import Path


SCREEN = (
    Path(__file__).resolve().parent.parent
    / "frontend/src/admin/IngestionScreen.tsx"
)


def _label_blocks(source: str) -> list[str]:
    """Every <label ...> ... </label> region, non-greedy."""
    return re.findall(r"<label\b.*?</label>", source, re.DOTALL)


class TestTheUploadFieldOpensItsPickerOnce:
    def test_the_file_input_exists(self):
        assert 'type="file"' in SCREEN.read_text()

    def test_no_label_encloses_a_file_input(self):
        offenders = [
            block
            for block in _label_blocks(SCREEN.read_text())
            if 'type="file"' in block
        ]

        assert offenders == [], (
            "A <label> wrapping the file input makes the picker open twice "
            "and cancel itself. Associate it with htmlFor/id instead."
        )

    def test_the_label_is_still_associated_with_the_input(self):
        """
        Dropping the wrapper must not drop the association: the label is
        what names the field for a screen reader, and what makes the
        caption clickable.
        """
        source = SCREEN.read_text()

        target = re.search(r'htmlFor="([^"]+)"', source)

        assert target, "the file field lost its label association"
        assert f'id="{target.group(1)}"' in source


class TestTheOtherFieldsAreLeftAlone:
    def test_the_company_select_may_stay_wrapped(self):
        """
        Nesting is correct for a select -- it has no second activation --
        so this rule is about the file input specifically and must not be
        applied across the form.
        """
        blocks = _label_blocks(SCREEN.read_text())

        assert any("<select" in block for block in blocks)
