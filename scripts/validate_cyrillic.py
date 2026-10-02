#!/usr/bin/env python3
"""Check TTF/CFF OTF coverage, style linking, shaping, marks and webfont parity."""
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
import ctypes as C
import ctypes.util
import json

ROOT=Path(__file__).resolve().parents[1]
REQUIRED=set(range(0x0400,0x0460)) | {0x0490,0x0491,0x0462,0x0463,0x2116,0x0301}
STYLES={'Regular':(400,False),'Italic':(400,True),'Bold':(700,False),'BoldItalic':(700,True)}

class Info(C.Structure):
    _fields_=[('glyph',C.c_uint32),('mask',C.c_uint32),('cluster',C.c_uint32),('var1',C.c_uint32),('var2',C.c_uint32)]
class Position(C.Structure):
    _fields_=[('advance',C.c_int32),('yadvance',C.c_int32),('x',C.c_int32),('y',C.c_int32),('var',C.c_uint32)]
class Feature(C.Structure):
    _fields_=[('tag',C.c_uint32),('value',C.c_uint32),('start',C.c_uint),('end',C.c_uint)]

hb=C.CDLL(ctypes.util.find_library('harfbuzz'))
def function(name,result,args):
    f=getattr(hb,name);f.restype=result;f.argtypes=args;return f
vp=C.c_void_p;u=C.c_uint;p=C.c_char_p
blob=function('hb_blob_create_from_file',vp,[p])
face=function('hb_face_create',vp,[vp,u])
font=function('hb_font_create',vp,[vp])
function('hb_ot_font_set_funcs',None,[vp]);function('hb_font_set_scale',None,[vp,C.c_int,C.c_int])
buffer=function('hb_buffer_create',vp,[])
function('hb_buffer_add_utf8',None,[vp,p,C.c_int,u,C.c_int]);function('hb_buffer_guess_segment_properties',None,[vp])
function('hb_shape',None,[vp,vp,C.POINTER(Feature),u]);function('hb_feature_from_string',C.c_bool,[p,C.c_int,C.POINTER(Feature)])
function('hb_buffer_get_glyph_infos',C.POINTER(Info),[vp,C.POINTER(u)])
function('hb_buffer_get_glyph_positions',C.POINTER(Position),[vp,C.POINTER(u)])
for kind in ['blob','face','font','buffer']:function('hb_'+kind+'_destroy',None,[vp])

def shape(path,text,features=()):
    bl=blob(str(path).encode());fa=face(bl,0);fo=font(fa);hb.hb_ot_font_set_funcs(fo);hb.hb_font_set_scale(fo,2000,2000)
    bu=buffer();raw=text.encode();hb.hb_buffer_add_utf8(bu,raw,len(raw),0,len(raw));hb.hb_buffer_guess_segment_properties(bu)
    fs=(Feature*len(features))()
    for i,s in enumerate(features):assert hb.hb_feature_from_string(s.encode(),-1,C.byref(fs[i]))
    hb.hb_shape(fo,bu,fs,len(features));n=u();info=hb.hb_buffer_get_glyph_infos(bu,C.byref(n));pos=hb.hb_buffer_get_glyph_positions(bu,C.byref(n))
    result=[(info[i].glyph,pos[i].advance,pos[i].x,pos[i].y) for i in range(n.value)]
    for kind,item in [('buffer',bu),('font',fo),('face',fa),('blob',bl)]:getattr(hb,'hb_'+kind+'_destroy')(item)
    return result

def breve_clearance(glyphs,glyph_name):
    drawing=DecomposingRecordingPen(glyphs)
    glyphs[glyph_name].draw(drawing)
    contours=[];part=[]
    for operation,arguments in drawing.value:
        part.append((operation,arguments))
        if operation in ('closePath','endPath'):
            pen=BoundsPen(glyphs);recording=RecordingPen();recording.value=part
            recording.replay(pen)
            if pen.bounds is not None:contours.append(pen.bounds)
            part=[]
    assert len(contours)>=2,(glyph_name,'missing body or breve')
    mark=max(contours,key=lambda bounds:bounds[1])
    body_top=max(bounds[3] for bounds in contours if bounds is not mark)
    return mark[1]-body_top


def validate_font(path,style,weight,italic,format_name):
    f=TTFont(path);cmap=f.getBestCmap();assert REQUIRED<=set(cmap)
    if format_name=='otf':
        assert f.sfntVersion=='OTTO' and 'CFF ' in f and 'glyf' not in f
        assert f['CFF '].cff.fontNames==[f['name'].getDebugName(6)]
    else:
        assert 'glyf' in f and 'CFF ' not in f
    gs=f.getGlyphSet()
    breve_gaps={name:breve_clearance(gs,name) for name in ('uni0419','uni0439','uni0419.sc')}
    em=f['head'].unitsPerEm
    for glyph,target in [('uni0419',0.10),('uni0439',0.06)]:
        assert abs(breve_gaps[glyph]-em*target)<=2,(path,glyph,breve_gaps[glyph])
    assert breve_gaps['uni0419.sc']>=em*0.05,(path,'smallcap breve clearance')
    for cp in REQUIRED:
        pen=BoundsPen(gs);gs[cmap[cp]].draw(pen);assert pen.bounds is not None,(style,hex(cp))
        bounds=pen.bounds;assert bounds[3]<=f['hhea'].ascent and bounds[1]>=f['hhea'].descent,(style,hex(cp),bounds)
    assert f['OS/2'].usWeightClass==weight
    assert bool(f['OS/2'].fsSelection&1)==italic
    assert f['name'].getDebugName(1)=='Libron Cyrillic'
    assert f['name'].getDebugName(16)=='Libron Cyrillic'
    version=(ROOT/'VERSION').read_text().strip()
    # ttfautohint appends its version after a semicolon in TrueType name ID 5.
    expected_version='Version '+version
    for record in f['name'].names:
        if record.nameID==5:
            assert record.toUnicode().split(';',1)[0]==expected_version,(path,record.toUnicode())
    assert abs(f['head'].fontRevision-float(version))<1/65536,(path,'fontRevision')
    assert ' ' not in f['name'].getDebugName(6)
    assert 'Literata' in f['name'].getDebugName(0)
    assert f['OS/2'].ulUnicodeRange1&(1<<9)
    assert f['OS/2'].ulCodePageRange1&(1<<2)
    for tag in ['GPOS','GSUB']:
        assert 'cyrl' in [r.ScriptTag for r in f[tag].table.ScriptList.ScriptRecord]
    for text in ['Съешь ещё этих мягких французских булок, да выпей чаю.','Ґанок, Європа, їжак, Іван, Ўладзімер','АВАТАР ТОЛЬКО ЛАДНО ГОД ЯФ']:
        assert all(g[0] for g in shape(path,text)),(style,text)
    stress=shape(path,'а\u0301');assert len(stress)==2 and stress[1][1]==0 and stress[1][2]!=0
    before=shape(path,'автор');after=shape(path,'автор',['smcp=1']);assert [r[0] for r in before]!=[r[0] for r in after]
    kerned=sum(r[1] for r in shape(path,'АТ ТА АУ УА ЛА ГА То'))
    unkerned=sum(r[1] for r in shape(path,'АТ ТА АУ УА ЛА ГА То',['kern=0']))
    assert kerned!=unkerned,(style,'kerning inactive')
    result={'style':style,'weight':weight,'glyphs':f['maxp'].numGlyphs,'unicode_characters':len(cmap),'coverage_checks':len(REQUIRED),'kerning_delta':kerned-unkerned,'accent_position':stress[1][2:],'short_i_breve_gaps':breve_gaps}
    f.close()
    return result

results={format_name:[] for format_name in ['ttf','otf']}
for style,(weight,italic) in STYLES.items():
    for format_name in results:
        path=ROOT/'out'/format_name/f'LibronCyrillic-{style}.{format_name}'
        results[format_name].append(validate_font(path,style,weight,italic,format_name))
    with TTFont(ROOT/'out/ttf'/f'LibronCyrillic-{style}.ttf') as ttf, TTFont(ROOT/'out/otf'/f'LibronCyrillic-{style}.otf') as otf, TTFont(ROOT/'out/web'/f'LibronCyrillic-{style}.woff2') as web:
        assert web.getBestCmap()==ttf.getBestCmap()
        assert set(otf.getBestCmap())==set(ttf.getBestCmap())
        for cp,glyph in ttf.getBestCmap().items():
            assert ttf['hmtx'][glyph][0]==otf['hmtx'][otf.getBestCmap()[cp]][0],(style,hex(cp),'advance mismatch')
print(json.dumps({'status':'passed','formats':results,'webfont_parity':'passed'},ensure_ascii=False,indent=2))
