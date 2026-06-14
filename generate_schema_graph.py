#!/usr/bin/env python3
"""Generate an ER diagram for Apple Photos Library SQLite schema."""

import graphviz

dot = graphviz.Digraph(
    'Photos_Library_Schema',
    format='png',
    engine='dot',
    graph_attr={
        'rankdir': 'LR',
        'bgcolor': '#1a1a2e',
        'fontname': 'Helvetica Neue',
        'pad': '0.5',
        'nodesep': '0.6',
        'ranksep': '1.2',
        'dpi': '200',
    },
    node_attr={
        'fontname': 'Helvetica Neue',
        'fontsize': '11',
        'shape': 'plain',
    },
    edge_attr={
        'fontname': 'Helvetica Neue',
        'fontsize': '9',
        'color': '#888888',
        'fontcolor': '#aaaaaa',
    },
)


def table_html(title, columns, color, title_bg):
    """Build an HTML-like label for a table node."""
    rows = ""
    for col_name, col_type, is_pk, is_fk in columns:
        icon = "🔑" if is_pk else ("🔗" if is_fk else "  ")
        type_color = "#888888"
        name_color = "#e0e0e0" if not is_fk else "#82aaff"
        rows += (
            f'<TR>'
            f'<TD ALIGN="LEFT" BGCOLOR="#16213e"><FONT COLOR="#666666">{icon}</FONT></TD>'
            f'<TD ALIGN="LEFT" BGCOLOR="#16213e"><FONT COLOR="{name_color}">{col_name}</FONT></TD>'
            f'<TD ALIGN="LEFT" BGCOLOR="#16213e"><FONT COLOR="{type_color}">{col_type}</FONT></TD>'
            f'</TR>'
        )
    return (
        f'<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="6" COLOR="{color}">'
        f'<TR><TD COLSPAN="3" BGCOLOR="{title_bg}"><B><FONT COLOR="white" POINT-SIZE="13">{title}</FONT></B></TD></TR>'
        f'{rows}'
        f'</TABLE>>'
    )


# ── ZASSET ──
dot.node('ZASSET', table_html('ZASSET', [
    ('Z_PK', 'INTEGER', True, False),
    ('ZUUID', 'VARCHAR', False, False),
    ('ZFILENAME', 'VARCHAR', False, False),
    ('ZDIRECTORY', 'VARCHAR', False, False),
    ('ZKIND', 'INTEGER', False, False),
    ('ZWIDTH / ZHEIGHT', 'INTEGER', False, False),
    ('ZDATECREATED', 'TIMESTAMP', False, False),
    ('ZADDEDDATE', 'TIMESTAMP', False, False),
    ('ZMODIFICATIONDATE', 'TIMESTAMP', False, False),
    ('ZTRASHEDSTATE', 'INTEGER', False, False),
    ('ZFAVORITE', 'INTEGER', False, False),
    ('ZHIDDEN', 'INTEGER', False, False),
    ('ZADDITIONALATTRIBUTES', 'INTEGER', False, True),
    ('ZMOMENT', 'INTEGER', False, True),
    ('ZIMPORTSESSION', 'INTEGER', False, True),
], '#e94560', '#c81d4e'))

# ── ZADDITIONALASSETATTRIBUTES ──
dot.node('ZADDATTR', table_html('ZADDITIONALASSETATTRIBUTES', [
    ('Z_PK', 'INTEGER', True, False),
    ('ZASSET', 'INTEGER', False, True),
    ('ZORIGINALFILENAME', 'VARCHAR', False, False),
    ('ZORIGINALFILESIZE', 'INTEGER', False, False),
    ('ZIMPORTEDBYBUNDLEID', 'VARCHAR', False, False),
    ('ZIMPORTEDBYDISPLAYNAME', 'VARCHAR', False, False),
    ('ZTIMEZONENAME', 'VARCHAR', False, False),
    ('ZREVERSELOCATIONDATA', 'BLOB', False, False),
    ('ZORIGINALHASH', 'BLOB', False, False),
], '#e94560', '#8b1a3a'))

# ── ZGENERICALBUM ──
dot.node('ZGENERICALBUM', table_html('ZGENERICALBUM', [
    ('Z_PK', 'INTEGER', True, False),
    ('ZUUID', 'VARCHAR', False, False),
    ('ZTITLE', 'VARCHAR', False, False),
    ('ZKIND', 'INTEGER', False, False),
    ('ZPARENTFOLDER', 'INTEGER', False, True),
    ('ZCREATIONDATE', 'TIMESTAMP', False, False),
    ('ZSTARTDATE / ZENDDATE', 'TIMESTAMP', False, False),
    ('ZCACHEDCOUNT', 'INTEGER', False, False),
    ('ZTRASHEDSTATE', 'INTEGER', False, False),
], '#0f3460', '#0a2647'))

# ── Z_33ASSETS (Join Table) ──
dot.node('Z_33ASSETS', table_html('Z_33ASSETS', [
    ('Z_33ALBUMS', 'INTEGER', False, True),
    ('Z_3ASSETS', 'INTEGER', False, True),
], '#533483', '#3a1f5e'))

# ── ZKEYWORD ──
dot.node('ZKEYWORD', table_html('ZKEYWORD', [
    ('Z_PK', 'INTEGER', True, False),
    ('ZTITLE', 'VARCHAR', False, False),
], '#0f3460', '#0a2647'))

# ── Z_1KEYWORDS (Join Table) ──
dot.node('Z_1KEYWORDS', table_html('Z_1KEYWORDS', [
    ('Z_1ASSETATTRIBUTES', 'INTEGER', False, True),
    ('Z_52KEYWORDS', 'INTEGER', False, True),
], '#533483', '#3a1f5e'))

# ── ZMOMENT ──
dot.node('ZMOMENT', table_html('ZMOMENT', [
    ('Z_PK', 'INTEGER', True, False),
    ('ZTITLE / ZSUBTITLE', 'VARCHAR', False, False),
    ('ZSTARTDATE / ZENDDATE', 'TIMESTAMP', False, False),
    ('ZAPPROX LAT / LNG', 'FLOAT', False, False),
    ('ZCACHEDCOUNT', 'INTEGER', False, False),
], '#0f3460', '#0a2647'))

# ── ZPERSON ──
dot.node('ZPERSON', table_html('ZPERSON', [
    ('Z_PK', 'INTEGER', True, False),
    ('ZDISPLAYNAME', 'VARCHAR', False, False),
    ('ZFULLNAME', 'VARCHAR', False, False),
    ('ZFACECOUNT', 'INTEGER', False, False),
    ('ZKEYFACE', 'INTEGER', False, True),
    ('ZVERIFIEDTYPE', 'INTEGER', False, False),
], '#e94560', '#8b1a3a'))

# ── ZDETECTEDFACE ──
dot.node('ZDETECTEDFACE', table_html('ZDETECTEDFACE', [
    ('Z_PK', 'INTEGER', True, False),
    ('ZASSETFORFACE', 'INTEGER', False, True),
    ('ZPERSONFORFACE', 'INTEGER', False, True),
    ('ZQUALITY', 'FLOAT', False, False),
    ('ZSIZE', 'FLOAT', False, False),
], '#533483', '#3a1f5e'))

# ── ZINTERNALRESOURCE ──
dot.node('ZINTRES', table_html('ZINTERNALRESOURCE', [
    ('Z_PK', 'INTEGER', True, False),
    ('ZASSET', 'INTEGER', False, True),
    ('ZRESOURCETYPE', 'INTEGER', False, False),
    ('ZDATALENGTH', 'INTEGER', False, False),
    ('ZFINGERPRINT', 'VARCHAR', False, False),
], '#0f3460', '#0a2647'))

# ── File System (visual node) ──
dot.node('FILESYSTEM', table_html('File System', [
    ('originals/&lt;dir&gt;/&lt;file&gt;', 'Original media', False, False),
    ('resources/', 'Thumbnails &amp; edits', False, False),
], '#2d6a4f', '#1b4332'))

# ── Edges ──
# Album <-> Asset (many-to-many via join)
dot.edge('ZGENERICALBUM', 'Z_33ASSETS', label=' Z_PK → Z_33ALBUMS', color='#5c7cfa', fontcolor='#5c7cfa')
dot.edge('Z_33ASSETS', 'ZASSET', label=' Z_3ASSETS → Z_PK', color='#5c7cfa', fontcolor='#5c7cfa')

# Album self-reference (folder hierarchy)
dot.edge('ZGENERICALBUM', 'ZGENERICALBUM', label='ZPARENTFOLDER\n(folder nesting)', color='#ffd43b', fontcolor='#ffd43b', style='dashed', constraint='false')

# Asset → Additional Attributes (1:1)
dot.edge('ZASSET', 'ZADDATTR', label=' 1:1', color='#ff6b6b', fontcolor='#ff6b6b')

# Additional Attributes → Keywords (via join)
dot.edge('ZADDATTR', 'Z_1KEYWORDS', label=' Z_PK → Z_1ASSETATTRIBUTES', color='#5c7cfa', fontcolor='#5c7cfa')
dot.edge('Z_1KEYWORDS', 'ZKEYWORD', label=' Z_52KEYWORDS → Z_PK', color='#5c7cfa', fontcolor='#5c7cfa')

# Asset → Moment
dot.edge('ZASSET', 'ZMOMENT', label=' ZMOMENT → Z_PK  (N:1)', color='#51cf66', fontcolor='#51cf66')

# Asset → DetectedFace → Person
dot.edge('ZASSET', 'ZDETECTEDFACE', label=' Z_PK ← ZASSETFORFACE  (1:N)', color='#cc5de8', fontcolor='#cc5de8')
dot.edge('ZDETECTEDFACE', 'ZPERSON', label=' ZPERSONFORFACE → Z_PK  (N:1)', color='#cc5de8', fontcolor='#cc5de8')

# Asset → InternalResource
dot.edge('ZASSET', 'ZINTRES', label=' Z_PK ← ZASSET  (1:N)', color='#ff922b', fontcolor='#ff922b')

# InternalResource → File System
dot.edge('ZINTRES', 'FILESYSTEM', label=' file variants', color='#2d6a4f', fontcolor='#51cf66', style='dashed')

# Asset → File System
dot.edge('ZASSET', 'FILESYSTEM', label=' ZDIRECTORY/ZFILENAME', color='#2d6a4f', fontcolor='#51cf66', style='dashed')

# Render
output_path = './docs/Photos_Library_Schema'
dot.render(output_path, cleanup=True)
print(f"Graph saved to {output_path}.png")
