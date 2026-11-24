"""Genuine grille form, source review and separate physical inventories."""
import copy,hashlib,io,sys,unittest,zipfile
from unittest.mock import patch
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
import abp_server as app
from abp_exhaust import EXHAUST_TEMPLATE,exhaust_errors
from abp_source_review import inventory_snapshot,source_review_approved
from abp_reference import reset_measurements
from test_source_review import payload


def exhaust_payload(count=1):
    p=payload();p['templates'].append(EXHAUST_TEMPLATE)
    p['exhaust_outlets']=[{'include':True,'type':'EAG-2','size':'8','system':'EF-7','location':'ROOM A',
        'design_cfm':90,'source':'synthetic.pdf','reference':'page 1','source_sha256':'a'*64,
        'evidence':'Original floor plan identifies this exhaust inlet and its fan connection.',
        'position':[10+n*10,20],'position_coordinate_space':'displayed_pdf_points','manual_locator':'NORTH INLET '+str(n+1),
        'quantity':1,'quantity_unresolved':False} for n in range(count)]
    p['source_review']['inventory']=inventory_snapshot(p)
    return p


class ExhaustTests(unittest.TestCase):
    def test_printed_callouts_are_separate_from_supply_and_can_be_saved_unassigned(self):
        from abp_outlets import centered_outlets
        def word(x,y,text,block):
            width=len(text)*4
            return (x-width/2,y,x+width/2,y+10,text,block,0,0)
        words=[word(30,50,'EAG-8',1),word(30,63,'125',1),
               word(100,50,'EAG-8',1),word(100,63,'250',1)]
        get=lambda sample: centered_outlets(sample,1,'synthetic.pdf',plan_confirmed=True,exhaust=True)
        self.assertEqual(centered_outlets(words,1,'synthetic.pdf',plan_confirmed=True),[])
        self.assertEqual(centered_outlets(words,1,'synthetic.pdf',exhaust=True),[])
        raw=get(words)
        self.assertEqual([r['design_cfm'] for r in raw],[125,250])
        for extra in ['EACH','TYP.','LEGEND','MEASURED','DEMO']:
            self.assertEqual(get(words[:2]+[word(30,33,extra,2)]),[])
        self.assertEqual(get([words[0],word(30,63,'125',4)]),[])
        self.assertEqual(get([*words[:2],word(30,65,'90',9)]),[])
        self.assertEqual(get([*words[:2],word(30,38,'MAX',1)]),[])
        p=exhaust_payload()
        for o in raw:
            o.update(source_sha256='a'*64,position_coordinate_space='displayed_pdf_points')
            self.assertFalse(o['include'])
            self.assertEqual((o['system'],o['location'],o['size'],o['manual_locator']),('','','',''))
        p['exhaust_outlets']=raw
        self.assertFalse(exhaust_errors(p,require_review=False))
        self.assertTrue(exhaust_errors(p))
        for o in raw:o['exclusion_note']='Source revision excludes this inlet.'
        self.assertFalse(exhaust_errors(p))
        raw[0]['include']=True
        self.assertTrue(exhaust_errors(p))

    def test_pdf_callouts_and_supervised_scan_routing(self):
        import pymupdf
        from abp_schedule import parse_pdf
        with pymupdf.open() as doc:
            p=doc.new_page()
            p.insert_text((60,40),'MECHANICAL FLOOR PLAN',fontsize=10)
            for x,top,mark,flow in [(80,110,'EAG-4','1,750'),(240,250,'SAG-2','2,250')]:
                for y,value in [(top,mark),(top+14.5,flow)]:
                    p.insert_text((x-pymupdf.get_text_length(value,fontname='cour',fontsize=10)/2,y),value,fontsize=10,fontname='cour')
            data=doc.tobytes()
        _,_,outlets=parse_pdf('plan.pdf',data)
        self.assertEqual(sorted((o['type'],o['design_cfm']) for o in outlets),[('EAG-4',1750),('SAG-2',2250)])
        if sys.platform!='linux':
            self.skipTest('PDF extraction passed. Production worker supervision requires Linux.')
        result=app.read_sources([('plan.pdf',data)])
        self.assertEqual(result['source_checkpoints'][0]['native_status'],'completed_native_stage')
        self.assertEqual([r['type'] for r in result['diffusers']],['SAG-2'])
        row,=result['exhaust_outlets']
        self.assertEqual((row['type'],row['design_cfm'],row['include']),('EAG-4',1750,False))
        self.assertEqual(row['source_sha256'],hashlib.sha256(data).hexdigest())
        self.assertEqual(row['position_coordinate_space'],'displayed_pdf_points')
        self.assertFalse(exhaust_errors({**result,'scan_state':result},require_review=False))

    def test_original_grilles_group_and_paginate_without_touching_formulas(self):
        p=exhaust_payload(30)
        p['records'].append({'tag':'EF-8','template':'Exhaust Fans _Sm._.xlsx','status':'VERIFIED','design_cfm':65})
        p['exhaust_outlets'].append({**copy.deepcopy(p['exhaust_outlets'][0]),'system':'EF-8','design_cfm':65,'position':[400,20],'manual_locator':'SOUTH'})
        p['source_review']['inventory']=inventory_snapshot(p);before=copy.deepcopy(p)
        self.assertTrue(source_review_approved(p));app.validate_payload(p)
        original=app.LOOKUP[EXHAUST_TEMPLATE].read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(),'0c2d4880fa1fd64f1974b7465f50ed115e21225d31714bcaf22d7837bcbcf77d')
        with patch.object(app,'BLANK_RECT_FORMS',1),patch.object(app,'BLANK_RND_FORMS',1):data=app.build(p)
        master=load_workbook(io.BytesIO(original));book=load_workbook(io.BytesIO(data))
        try:
            src=master.active;ws=book['EXHAUST GRILLS']
            self.assertEqual(ws.max_row,120)
            self.assertEqual([ws[f'A{r}'].value for r in (6,46,86)],['EF-7','EF-7','EF-8'])
            self.assertEqual([ws[f'B{r}'].value for r in (7,35,47,87)],[1,29,30,1])
            self.assertEqual([ws[f'F{r}'].value for r in (7,35,47,87)],[90,90,90,65])
            self.assertNotIn('SUPPLY DIFFUSERS',book.sheetnames)
            self.assertTrue(any('RECT' in s.title for s in book));self.assertTrue(any('RND' in s.title for s in book))
            self.assertEqual(ws.page_setup,src.page_setup);self.assertEqual(ws.page_margins,src.page_margins)
            for off in (0,40,80):
                for row in src:
                    for original_cell in row:
                        target=ws.cell(original_cell.row+off,original_cell.column)
                        if original_cell.data_type=='f':self.assertEqual(target.value,Translator(original_cell.value,origin=original_cell.coordinate).translate_formula(target.coordinate))
                        else:self.assertNotEqual(target.data_type,'f',target.coordinate) # No invented total or percentage formulas.
                        for attr in ('font','fill','border','alignment','number_format','protection'):
                            self.assertEqual(copy.copy(getattr(target,attr)),copy.copy(getattr(original_cell,attr)),target.coordinate)
                for r in range(7,36):
                    for c in ('E','G'):self.assertIsNone(ws[f'{c}{r+off}'].value)
                for r in (1,2):self.assertIsNone(ws[f'G{r+off}'].value)
                self.assertIsNone(ws[f'B{37+off}'].value)
                for r,dim in src.row_dimensions.items():
                    self.assertEqual({k:v for k,v in dict(dim).items() if k!='s'}, {k:v for k,v in dict(ws.row_dimensions[r+off]).items() if k!='s'})
            with zipfile.ZipFile(io.BytesIO(original)) as z:images={hashlib.sha256(z.read(n)).digest() for n in z.namelist() if '/media/' in n}
            with zipfile.ZipFile(io.BytesIO(data)) as z:copied={hashlib.sha256(z.read(n)).digest() for n in z.namelist() if '/media/' in n}
            self.assertTrue(images);self.assertTrue(images<=copied)
        finally:master.close();book.close()
        self.assertEqual(p,before)

    def test_original_preliminary_actuals_and_signoff_clear_without_new_calculations(self):
        master=load_workbook(app.LOOKUP[EXHAUST_TEMPLATE]);ws=master.active
        try:
            formulas={c.coordinate:c.value for row in ws for c in row if c.data_type=='f'}
            ws['E7']=87;ws['G7']=88;ws['G1']='OLD TECH';ws['G2']='OLD DATE';ws['F7']=90
            reset_measurements(ws)
            for c in ('E7','G7','G1','G2'):self.assertIsNone(ws[c].value,c)
            self.assertEqual(ws['F7'].value,90)
            self.assertEqual({c.coordinate:c.value for row in ws for c in row if c.data_type=='f'},formulas)
        finally:master.close()

    def test_inlet_source_connection_and_classification_fail_closed(self):
        cases=[lambda p:p['exhaust_outlets'][0].update(source_sha256='b'*64),
            lambda p:p['exhaust_outlets'][0].update(reference='page 3'),
            lambda p:p['exhaust_outlets'][0].update(quantity=True),
            lambda p:p['exhaust_outlets'][0].update(quantity=2),
            lambda p:p['exhaust_outlets'][0].update(design_cfm=True),
            lambda p:p['exhaust_outlets'][0].update(design_cfm='NaN'),
            lambda p:p['exhaust_outlets'][0].update(actual_cfm=88),
            lambda p:p['exhaust_outlets'][0].update(type='SAG-1'),
            lambda p:p['exhaust_outlets'][0].update(system='EF-88'),
            lambda p:p['exhaust_outlets'][0].update(evidence='ok'),
            lambda p:p['exhaust_outlets'][0].update(position=[True,20]),
            lambda p:p['exhaust_outlets'][0].update(manual_locator='X'*121),
            lambda p:p['exhaust_outlets'].append(copy.deepcopy(p['exhaust_outlets'][0])),
            lambda p:p['diffusers'].append(copy.deepcopy(p['exhaust_outlets'][0])),
            lambda p:p['templates'].remove(EXHAUST_TEMPLATE)]
        for change in cases:
            p=exhaust_payload();change(p);p['source_review']['inventory']=inventory_snapshot(p)
            self.assertTrue(exhaust_errors(p));self.assertFalse(source_review_approved(p))
            with self.assertRaises(ValueError):app.validate_payload(p)
        for key in ('records','exhaust_outlets','diffusers','templates'):
            for value in (None,{},'bad'):
                p=exhaust_payload();p[key]=value;self.assertTrue(exhaust_errors(p))
        for key in ('records','exhaust_outlets','diffusers'):
            p=exhaust_payload();p[key]=[None];self.assertTrue(exhaust_errors(p))

    def test_approval_changes_and_partial_ack_cannot_bypass_source_identity(self):
        for key,value in [('design_cfm',91),('evidence','Different original source evidence for this inlet.'),('source_sha256','b'*64),('manual_locator','OTHER INLET')]:
            p=exhaust_payload();p['exhaust_outlets'][0][key]=value
            self.assertFalse(source_review_approved(p),key)
        p=exhaust_payload();p.pop('source_review');p['exhaust_outlets'][0]['source_sha256']='b'*64
        p['scan_acknowledgement']={'acknowledged':True,'note':'I accept an incomplete partial report.','scan_state':p['scan_state']}
        with self.assertRaisesRegex(ValueError,'source changed'):app.validate_payload(p)
        p=exhaust_payload();p['exhaust_outlets'][0]['include']=False;p['source_review']['inventory']=inventory_snapshot(p)
        self.assertFalse(source_review_approved(p));p['exhaust_outlets'][0]['exclusion_note']='Confirmed duplicate source annotation of the same physical inlet.'
        p['source_review']['inventory']=inventory_snapshot(p);self.assertTrue(source_review_approved(p))
        p=exhaust_payload();p['records'][0]['status']='UNVERIFIED';p['source_review']['inventory']=inventory_snapshot(p)
        self.assertTrue(exhaust_errors(p));self.assertFalse(source_review_approved(p))
        p.pop('source_review');p['scan_acknowledgement']={'acknowledged':True,'note':'I accept an incomplete partial report.','scan_state':p['scan_state']}
        with self.assertRaisesRegex(ValueError,'verified exhaust fan'):app.validate_payload(p)


if __name__=='__main__':unittest.main()
