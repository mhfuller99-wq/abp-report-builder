"""Repeated annotations are not physical takeoffs until explicitly reviewed."""
import copy
import json
import unittest
from abp_outlets import distinct_outlets
from abp_outlet_instances import outlet_instance_errors
from abp_ocr import diffuser_candidates
from abp_ocr_candidates import merge_diffuser_candidate,reconcile_diffuser_sources,retain_image_quantity_guards


def repeated_rows(count=3):
    parent={'include':False,'source':'synthetic.pdf','reference':'page 1','position':[100,100],
            'type':'R-7','design_cfm':180,'system':'AHU-7','location':'ROOM A','size':'12x6',
            'quantity':count,'quantity_unresolved':True,'exclusion_note':'Replaced by individually reviewed physical outlets.'}
    group=json.dumps([parent[k] for k in ('source','reference','position')],separators=(',',':'))
    locators=[f'ROOM A / POSITION {i}' for i in range(1,count+1)]
    rows=[dict(parent,include=True,quantity=1,quantity_unresolved=False,exclusion_note='',
          location=locator,repeat_instance={'group':group,'index':i,'locator':locator})
          for i,locator in enumerate(locators,1)]
    parent['repeat_resolution']={'group':group,'locators':locators,
         'source_quantity':count,'source_quantity_candidates':[],
         'note':'Checked each physical symbol and per-outlet CFM on the original plan.'}
    return [parent,*rows]


class RepeatedOutletTests(unittest.TestCase):
    def test_quantity_survives_overlap_and_conflicting_later_readings(self):
        base={'source':'test.pdf','reference':'page 1','position':[100,100],'type':'R-7','design_cfm':180}
        rows=[dict(base),dict(base,quantity=20,quantity_unresolved=True)]
        found=distinct_outlets(rows)
        self.assertEqual(len(found),1);self.assertEqual(found[0]['quantity'],20)
        self.assertTrue(found[0]['quantity_unresolved'])
        found=distinct_outlets([found[0],dict(base,quantity=30,quantity_unresolved=True),dict(base,quantity=20,quantity_unresolved=True)])
        self.assertNotIn('quantity',found[0]);self.assertEqual(found[0]['quantity_candidates'],[20,30])
        nearby=dict(base,position=[120,100])
        self.assertEqual(len(distinct_outlets([found[0],nearby])),2)

    def test_ocr_retains_quantity_without_generating_twenty_devices(self):
        def w(x,y,t):return {'box':[x,y,x+len(t)*4,y+9],'text':t,'confidence':95}
        words=[w(0,0,'HVAC'),w(20,0,'PLAN'),w(100,100,'SA'),w(80,112,'180'),w(96,112,'CFM'),w(90,124,'(TYP-20)')]
        found=diffuser_candidates(words,'synthetic.pdf',1)
        self.assertEqual(len(found),1);self.assertEqual(found[0]['quantity'],20)
        self.assertFalse(found[0]['include']);self.assertTrue(found[0]['quantity_unresolved'])
        unmarked=copy.deepcopy(found[0]);unmarked.pop('quantity');unmarked.pop('quantity_unresolved')
        existing=[unmarked];self.assertTrue(merge_diffuser_candidate(existing,found[0]))
        self.assertEqual(existing[0]['quantity'],20)
        conflict=dict(found[0],quantity=30)
        self.assertTrue(merge_diffuser_candidate(existing,conflict))
        self.assertTrue(merge_diffuser_candidate(existing,found[0]))
        self.assertNotIn('quantity',existing[0]);self.assertEqual(existing[0]['quantity_candidates'],[20,30])

    def test_complete_review_valid_and_missing_or_mutated_rows_rejected(self):
        self.assertEqual(outlet_instance_errors(repeated_rows()),[])
        changes=[lambda r:r.pop(),lambda r:r.append(copy.deepcopy(r[1])),lambda r:r.pop(0),
                 lambda r:r[1].update(position=[101,100]),lambda r:r[1]['repeat_instance'].update(locator='WRONG ROOM'),
                 lambda r:r[1]['repeat_instance'].update(index=0),lambda r:r[0].update(include=True),
                 lambda r:r[0]['repeat_resolution'].update(locators=['A','A','B']),
                 lambda r:r[0]['repeat_resolution'].update(source_quantity_candidates='20'),
                 lambda r:r[1].update(repeat_resolution=copy.deepcopy(r[0]['repeat_resolution']))]
        for change in changes:
            with self.subTest(change=change):
                rows=repeated_rows();change(rows);self.assertTrue(outlet_instance_errors(rows))

    def test_duplicate_image_repeat_marker_cannot_disappear_behind_native_row(self):
        native={'include':False,'source':'synthetic.pdf','reference':'page 1','position':[100,100],
                'position_coordinate_space':'displayed_pdf_points','type':'SA','size':'8','design_cfm':180}
        image={'kind':'diffuser','include':False,'source':'synthetic.pdf','page':1,'position':[101,100],
               'position_coordinate_space':'displayed_pdf_points','status':'UNVERIFIED','type':'SA','size':'8',
               'review_values':{'design_cfm':180},'quantity':20,'quantity_unresolved':True}
        saved=copy.deepcopy(native)
        reconcile_diffuser_sources([native],[image]);self.assertEqual(native,saved)
        retain_image_quantity_guards([native],[image])
        self.assertEqual(native['quantity'],20);self.assertTrue(native['quantity_unresolved']);self.assertFalse(native['include'])
        self.assertEqual({k:native[k] for k in saved},saved)
        other=dict(saved,position=[120,100]);retain_image_quantity_guards([other],[image])
        self.assertNotIn('quantity',other)
        ambiguous=[copy.deepcopy(saved),copy.deepcopy(saved)]
        retain_image_quantity_guards(ambiguous,[image]);self.assertEqual(ambiguous,[saved,saved])
        reviewed=dict(saved,include=True);retain_image_quantity_guards([reviewed],[image]);self.assertNotIn('quantity',reviewed)

    def test_partial_report_acknowledgement_cannot_bypass_quantity_guard(self):
        from abp_server import validate_payload
        p={'project':'SYNTHETIC','location':'TEST','templates':['Supply Diffusers.xlsx'],
           'records':[],'diffusers':[dict(repeated_rows()[0],include=True)],
           'scan_acknowledgement':{'acknowledged':True,'note':'I accept incomplete source coverage.'}}
        with self.assertRaisesRegex(ValueError,'repeated'):validate_payload(p)
        p['diffusers']=repeated_rows();validate_payload(p)
        p['diffusers'].pop()
        with self.assertRaisesRegex(ValueError,'missing or duplicated'):validate_payload(p)

    def test_source_approval_binds_resolution_basis(self):
        from abp_source_review import inventory_snapshot,source_review_approved
        from test_source_review import payload
        p=payload();p['templates'].extend(['Supply Diffusers.xlsx','Air Moving Equipment.xlsx'])
        p['records'].append({'tag':'AHU-7','template':'Air Moving Equipment.xlsx','status':'VERIFIED'})
        p['diffusers']=repeated_rows();p['source_review']['inventory']=inventory_snapshot(p)
        self.assertTrue(source_review_approved(p))
        p['diffusers'][0]['repeat_resolution']['note']='Changed the physical outlet interpretation.'
        self.assertFalse(source_review_approved(p))

    def test_workbook_has_every_physical_row_and_original_totals(self):
        import io
        from unittest.mock import patch
        from openpyxl import load_workbook
        import abp_server as app
        p={'project':'SYNTHETIC','location':'TEST','templates':['Supply Diffusers.xlsx'],
           'records':[],'diffusers':repeated_rows(3)}
        with patch.object(app,'BLANK_RECT_FORMS',1),patch.object(app,'BLANK_RND_FORMS',1):raw=app.build(p)
        wb=load_workbook(io.BytesIO(raw));s=wb['SUPPLY DIFFUSERS']
        locations=[c.value for row in s for c in row if isinstance(c.value,str) and c.value.startswith('ROOM A / POSITION')]
        self.assertEqual(sorted(locations),[f'ROOM A / POSITION {i}' for i in (1,2,3)])
        source=load_workbook(app.LOOKUP['Supply Diffusers.xlsx']).active
        for row in source:
            for c in row:
                if c.data_type=='f':self.assertEqual(s[c.coordinate].value,c.value)
        self.assertEqual(sum(c.value==180 for row in s for c in row),3)


if __name__=='__main__':unittest.main()
