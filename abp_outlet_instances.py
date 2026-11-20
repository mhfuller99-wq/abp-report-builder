"""Validate explicit human resolution of a repeated source callout."""
import json
import math


def outlet_instance_errors(outlets):
    errors=[];parents={};children={}
    def text(value,low=1,high=120):return isinstance(value,str) and low<=len(value.strip())<=high
    for row in outlets:
        if not isinstance(row,dict):errors.append('Invalid outlet instance');continue
        if row.get('include') is not False and (row.get('quantity_unresolved') or row.get('quantity',1)!=1):
            errors.append('Resolve the repeated outlet count into reviewed physical rows before including it')
        parent=row.get('repeat_resolution');child=row.get('repeat_instance')
        if parent is not None:
            if not isinstance(parent,dict):errors.append('Invalid repeated callout review');continue
            group=parent.get('group');locations=parent.get('locators')
            try:identity=json.loads(group) if isinstance(group,str) and len(group)<=600 else None
            except (ValueError,TypeError):identity=None
            position=row.get('position');count=parent.get('source_quantity');candidates=parent.get('source_quantity_candidates')
            valid_source=(text(row.get('source'),1,160) and text(row.get('reference'))
                          and isinstance(position,list) and len(position)==2
                          and all(type(n) in (int,float) and math.isfinite(n) for n in position))
            valid_witness=('source_quantity' in parent and (count is None or type(count)==int and count>1)
                           and isinstance(candidates,list) and len(candidates)<=100
                           and all(type(n)==int and n>1 for n in candidates))
            if (not valid_source or not valid_witness or identity!=[row.get('source'),row.get('reference'),position]
                or not isinstance(locations,list) or not 2<=len(locations)<=100
                or any(not text(x) for x in locations)
                or len({x.strip().upper() for x in locations})!=len(locations)
                or type(row.get('quantity'))!=int or row['quantity']!=len(locations)
                or row.get('include') is not False or not text(parent.get('note'),10,500)):
                errors.append('Repeated callout needs its reviewed count, original source and distinct physical locators');continue
            if group in parents:errors.append('Duplicate repeated callout review')
            parents[group]=(row,parent)
        if child is not None:
            if not isinstance(child,dict) or not text(child.get('group'),1,600) or type(child.get('index'))!=int:
                errors.append('Invalid repeated outlet identity');continue
            children.setdefault(child['group'],[]).append(row)
    for group in parents.keys()|children.keys():
        if group not in parents:errors.append('Repeated outlets lost their original callout review');continue
        original,parent=parents[group];rows=children.get(group,[]);locators=parent['locators']
        indices=[r['repeat_instance']['index'] for r in rows]
        if sorted(indices)!=list(range(1,len(locators)+1)):
            errors.append('Repeated callout physical rows are missing or duplicated');continue
        for row in rows:
            instance=row['repeat_instance'];index=instance['index']
            if (instance.get('locator')!=locators[index-1]
                or any(row.get(k)!=original.get(k) for k in ('source','reference','position'))
                or row.get('quantity')!=1 or row.get('quantity_unresolved') is not False
                or row.get('repeat_resolution') is not None):
                errors.append('Repeated outlet source identity changed; review the callout again')
    return list(dict.fromkeys(errors))
