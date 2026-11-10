"""Explicit review of partial coverage; never a takeoff or equipment approval."""
import textwrap


def partial_review_allowed(state, acknowledgement):
    if state.get('status') != 'incomplete' or not state.get('source_checkpoints'):
        return False
    if not any(c.get('native_status') == 'completed_native_stage' for c in state['source_checkpoints']):
        return False
    if not isinstance(acknowledgement, dict) or acknowledgement.get('acknowledged') is not True:
        return False
    note = acknowledgement.get('note')
    return (isinstance(note, str) and 20 <= len(note.strip()) <= 1000
            and acknowledgement.get('scan_state') == state)


def partial_review_lines(state, acknowledgement):
    """Fit disclosures into existing comment inputs without resizing the form."""
    if not partial_review_allowed(state, acknowledgement):
        return []
    items = ['REVIEWED PARTIAL REPORT. SOURCE SCAN INCOMPLETE. NOT FIELD READY.',
             'Manual review note: ' + acknowledgement['note'].strip(),
             'This acknowledgment does not verify equipment, drawings or measurements.']
    for c in state['source_checkpoints']:
        items.append(c['name'] + ': native ' + c['native_status'] + '; image ' + c['image_status']
                     + ('. ' + c['reason'] if c.get('reason') else ''))
    items.extend('Scan warning: ' + w for w in state['warnings'])
    lines = [line for item in items for line in textwrap.wrap(item, width=54,
            replace_whitespace=True, drop_whitespace=True)]
    if len(lines) > 360:
        raise ValueError('Too many coverage notes for a partial report. Split the source set; no disclosure was truncated.')
    return lines
