"""Explicit review of partial coverage; never a takeoff or equipment approval."""
import re
import textwrap


def _compact_page_warnings(warnings, sources):
    """Group only identical, explicitly source-qualified page messages on overflow."""
    counts = {}
    for entry in sources:
        name = entry['name']
        counts[name] = None if name in counts else entry.get('pages')
    groups = {}
    order = []
    for warning in warnings:
        name, separator, body = warning.partition(': ')
        limit = counts.get(name)
        if not separator or type(limit) is not int:
            order.append(warning)
            continue
        # Preserve a repeated filename prefix if emitted by a second reader.
        prefix = name + separator
        if body.startswith(prefix):
            body = body[len(prefix):]
            prefix += prefix
        match = re.fullmatch(r'([Pp]age) ([1-9]\d{0,2})(: .+| .+)', body)
        if not match or int(match[2]) > limit:
            order.append(warning)
            continue
        key = prefix, match[1], match[3]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(int(match[2]))

    for entry in order:
        if isinstance(entry, str):
            yield entry
            continue
        prefix, label, tail = entry
        pages = groups[entry]
        if len(pages) == 1:
            yield f'{prefix}{label} {pages[0]}{tail}'
            continue
        ranges = []
        first = last = pages[0]
        for value in pages[1:]:
            if value != last + 1:
                ranges.append(str(first) if first == last else f'{first}-{last}')
                first = value
            last = value
        ranges.append(str(first) if first == last else f'{first}-{last}')
        message = tail[2:] if tail.startswith(': ') else tail[1:]
        yield f'{prefix}{label}s {", ".join(ranges)} | {message}'


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
    def wrap_with(warnings):
        all_items = items + ['Scan warning: ' + w for w in warnings]
        return [line for item in all_items for line in textwrap.wrap(item, width=54,
                replace_whitespace=True, drop_whitespace=True)]
    lines = wrap_with(state['warnings'])
    if len(lines) > 360:
        lines = wrap_with(_compact_page_warnings(state['warnings'], state['source_checkpoints']))
    if len(lines) > 360:
        raise ValueError('Too many coverage notes for a partial report. Split the source set; no disclosure was truncated.')
    return lines
