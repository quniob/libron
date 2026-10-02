#!/usr/bin/env python3
"""Rebuild Libron's Cyrillic extension from immutable Libron and Literata inputs.
Run with Python from ghcr.io/nicoverbruggen/fntbld-oci:latest.
"""
from pathlib import Path
import fontforge
import pathops
import json
import math
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'cyrillic/config.json').read_text())
LANGS = (('DFLT', ('dflt',)), ('latn', ('dflt', 'MOL ', 'ROM ')),
         ('cyrl', ('dflt', 'RUS ', 'UKR ', 'BEL ', 'SRB ', 'MKD ', 'BGR ')))
CLONES = dict(zip('АВЕКМНОРСТХаеорсхуІіЈјЅѕ',
                  'ABEKMHOPCTXaeop cxyIiJjSs'.replace(' ', '')))
CLONES.update({'Ё':'Edieresis','ё':'edieresis','Ї':'Idieresis','ї':'idieresis'})
ACCENTS = {
 0x0400: (0x0415, 0x0300),
 0x0403: (0x0413, 0x0301),
 0x040C: (0x041A, 0x0301), 0x040D: (0x0418, 0x0300),
 0x040E: (0x0423, 0x0306), 0x0419: (0x0418, 0x0306),
 0x0450: (0x0435, 0x0300),
 0x0453: (0x0433, 0x0301),
 0x045C: (0x043A, 0x0301), 0x045D: (0x0438, 0x0300),
 0x045E: (0x0443, 0x0306), 0x0439: (0x0438, 0x0306),
}
COVERAGE = list(range(0x0400, 0x0460)) + [0x0490, 0x0491, 0x0462, 0x0463]


def name(cp):
    return f'uni{cp:04X}'


def geometry(g):
    """Get standalone outlines without introducing donor references."""
    g.unlinkRef()
    return g.foreground


def place_anchors(g, font, capital, cfg):
    bb = g.boundingBox()
    template = font['H' if capital else 'o']
    top = template.boundingBox()[3]
    center = (bb[0] + bb[2]) / 2
    g.anchorPoints = (('Anchor-0', 'base', center, top),
                      ('Anchor-4', 'base', center - cfg['base_slope'] * top / 2, 0))


def adopt(font, donor, cp, cfg):
    src = donor[cp]
    g = font.createChar(cp, name(cp))
    capital = unicodedata.category(chr(cp)) == 'Lu' or cp == 0x2116
    prefix = 'cap' if capital else 'lower'
    sx, sy = cfg[prefix+'_sx'], cfg[prefix+'_sy']
    advance = cfg[prefix+'_advance']
    # Measure stem slant, rather than trusting Literata's italic-angle metadata.
    shear = cfg['base_slope'] * sy - cfg['donor_slope'] * sx
    g.foreground = geometry(src)
    g.transform((sx, 0, shear, sy, 0, 0))
    g.transform((1, 0, 0, 1, (advance-sx)*src.width/2, 0))
    g.width = round(src.width*advance)
    place_anchors(g, font, capital, cfg)
    return g


def clone(font, cp, latin, cfg):
    base = font[latin]
    g = font.createChar(cp, name(cp))
    g.addReference(latin)
    g.width = base.width
    g.anchorPoints = base.anchorPoints
    if not g.anchorPoints:
        place_anchors(g, font, chr(cp).isupper(), cfg)
    return g


def accent(font, cp, base_cp, mark_cp, cfg):
    base = font[base_cp]
    g = font.createChar(cp, name(cp))
    capital = chr(cp).isupper()
    mark = font[mark_cp].glyphname + ('.case' if capital else '')
    g.addReference(base.glyphname)
    x = next((p[2] for p in base.anchorPoints if p[0]=='Anchor-0'), base.width/2)
    if not capital:
        x = base.width/2 + cfg['base_slope']*font['o'].boundingBox()[3]/2
    g.addReference(mark, (1, 0, 0, 1, x, 0))
    g.width = base.width
    g.anchorPoints = tuple(p for p in base.anchorPoints if p[0] != 'Anchor-0')
    return g


def expand_features(font):
    for lookup in font.gsub_lookups + font.gpos_lookups:
        typ, flags, features = font.getLookupInfo(lookup)
        extended=[]
        for tag, scripts in features:
            if tag in ['kern','mark','mkmk','smcp','c2sc','case']:
                if not any(s[0]=='cyrl' for s in scripts):
                    scripts = tuple(scripts) + (('cyrl', ('dflt','RUS ','UKR ','BEL ','SRB ','MKD ','BGR ')),)
            extended.append((tag,scripts))
        font.lookupSetFeatureList(lookup,tuple(extended))


def expand_native_kerning(font, aliases):
    originals = {}
    for original, names in aliases.items():
        originals[original] = tuple(names)
    # Extend original kerning classes; all Latin pairs and values stay intact.
    for lookup in font.gpos_lookups:
        for sub in font.getLookupSubtables(lookup):
            if not font.isKerningClass(sub):
                continue
            first, second, offsets = font.getKerningClass(sub)
            def extend(classes):
                return tuple(None if cls is None else tuple(cls) + tuple(
                    added for old in cls for added in originals.get(old, ())) for cls in classes)
            font.alterKerningClass(sub, extend(first), extend(second), offsets)
    # Explicit exceptions need the same alias expansion.
    exceptions = [(g.glyphname,p) for g in font.glyphs()
                  for p in g.getPosSub('*') if p[1]=='Pair']
    for left,p in exceptions:
        sub,_,right,*values=p
        for a in (left,)+originals.get(left,()):
            for b in (right,)+originals.get(right,()):
                if (a,b)!=(left,right):
                    font[a].addPosSub(sub,b,*values)


def donor_kerning(font, donor, mapping, imported, cfg):
    font.addLookup('Cyrillic kerning', 'gpos_pair', ('ignore_marks',), (('kern', LANGS),))
    sub='Cyrillic kerning pairs'
    font.addLookupSubtable('Cyrillic kerning',sub)
    pairs={}
    for lookup in donor.gpos_lookups:
        for table in donor.getLookupSubtables(lookup):
            if not donor.isKerningClass(table):
                continue
            first, second, offsets = donor.getKerningClass(table)
            for i,left in enumerate(first):
                if not left:continue
                for j,right in enumerate(second):
                    value=offsets[i*len(second)+j]
                    if not right or not value:continue
                    for a in left:
                        if a not in mapping:continue
                        for b in right:
                            if b in mapping and (a in imported or b in imported):
                                pairs[(a,b)]=value
    for g in donor.glyphs():
        a=g.glyphname
        if a not in mapping:continue
        for p in g.getPosSub('*'):
            if p[1]=='Pair' and p[2] in mapping and (a in imported or p[2] in imported):
                pairs[(a,p[2])]=p[5]
    for (a,b),value in pairs.items():
        left,right=mapping[a],mapping[b]
        scale=cfg['cap_advance'] if font[left].unicode>0 and chr(font[left].unicode).isupper() else cfg['lower_advance']
        value=round(value*scale)
        if value:font[left].addPosSub(sub,right,value)
    return len(pairs)


def smallcaps(font, cfg, style, aliases):
    sc_lookup="'smcp' Lowercase to Small Capitals in Latin"
    cc_lookup="'c2sc' Capitals to Small Capitals in Latin"
    sc_sub=font.getLookupSubtables(sc_lookup)[0]
    cc_sub=font.getLookupSubtables(cc_lookup)[0]
    ratio=font['o'].boundingBox()[3]*1.07/font['H'].boundingBox()[3]
    embolden={'Regular':28,'Bold':36,'Italic':20,'BoldItalic':32}[style]
    # FontForge's stroke offsetter requires cubic layers. Converting the
    # shared layer also prevents mixing cubic and quadratic spline objects.
    font.layers[1].is_quadratic = False
    for cp in COVERAGE:
        if not chr(cp).isupper():continue
        base=font[cp];sc=font.createChar(-1,base.glyphname+'.sc')
        latin=CLONES.get(chr(cp))
        if latin and latin+'.sc' in font:
            sc.addReference(latin+'.sc');sc.width=font[latin+'.sc'].width
            aliases.setdefault(latin+'.sc',[]).append(sc.glyphname)
        else:
            sc.foreground=geometry(base)
            sc.transform((ratio,0,0,ratio,0,0))
            sc.changeWeight(embolden,'auto');sc.addExtrema()
            outline=pathops.Path()
            sc.draw(outline.getPen())
            clean=pathops.simplify(outline,keep_starting_points=False)
            pen=sc.glyphPen(replace=True)
            clean.draw(pen)
            pen=None
            sc.round()
            sc.transform((1,0,0,1,20,0));sc.width=round(base.width*ratio)+40
        base.addPosSub(cc_sub,sc.glyphname)
        low=chr(cp).lower()
        if len(low)==1 and ord(low) in COVERAGE:
            font[ord(low)].addPosSub(sc_sub,sc.glyphname)



def build(style,cfg):
    font=fontforge.open(str(ROOT/'cyrillic/base'/f'Libron-{style}.sfd'))
    donor=fontforge.open(str(ROOT/'cyrillic'/f'Literata-{style}.ttf'))
    donor.selection.all();donor.unlinkReferences()
    aliases={};mapping={};imported=set()
    for cp in COVERAGE:
        if cp in ACCENTS:continue
        latin=CLONES.get(chr(cp))
        if latin:
            clone(font,cp,latin,cfg);aliases.setdefault(latin,[]).append(name(cp))
        else:
            if cp not in donor:raise ValueError(f'Donor missing U+{cp:04X}')
            adopt(font,donor,cp,cfg);imported.add(donor[cp].glyphname)
        mapping[donor[cp].glyphname]=name(cp)
    for cp,(base,mark) in ACCENTS.items():
        accent(font,cp,base,mark,cfg)
        if cp in donor:
            mapping[donor[cp].glyphname]=name(cp)
        original=CLONES.get(chr(base))
        if original:aliases.setdefault(original,[]).append(name(cp))
        elif cp in donor:imported.add(donor[cp].glyphname)
    # Punctuation pairs work for Cyrillic and for mixed-script text.
    for cp in list(range(32,127))+[0x2018,0x2019,0x201C,0x201D,0x2014,0x2013,0x00AB,0x00BB]:
        if cp in font and cp in donor:mapping[donor[cp].glyphname]=font[cp].glyphname
    smallcaps(font,cfg,style,aliases)
    expand_native_kerning(font,aliases)
    kern_count=donor_kerning(font,donor,mapping,imported,cfg)
    expand_features(font)
    # Enable Latin, Cyrillic and combining-mark Unicode ranges and code pages.
    ranges = list(font.os2_unicoderanges)
    ranges[0] |= (1 << 9) | (1 << 6)
    font.os2_unicoderanges = tuple(ranges)
    pages = list(font.os2_codepages)
    pages[0] |= (1 << 2)
    font.os2_codepages = tuple(pages)
    font.save(str(ROOT/'src'/f'Libron-{style}.sfd'))
    print(style,'Cyrillic glyphs',len(COVERAGE),'kerning pairs',kern_count,flush=True)
    donor.close();font.close()


if __name__=='__main__':
    for style,cfg in CONFIG.items():build(style,cfg)
