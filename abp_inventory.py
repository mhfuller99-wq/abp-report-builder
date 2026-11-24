"""Physical quantities under a shared printed equipment tag.

Review keeps one source record per tag. The writer receives one instance per
physical unit, with the original tag and the reviewed room/area on its form.
"""
import math


def quantity(record):
    value=record.get('quantity')
    if value in (None,''):return 1
    if isinstance(value,bool):raise ValueError('Equipment quantity must be a whole number from 1 to 100')
    try:number=float(value)
    except (TypeError,ValueError):raise ValueError('Equipment quantity must be a whole number from 1 to 100') from None
    if not math.isfinite(number) or not number.is_integer() or not 1<=number<=100:
        raise ValueError('Equipment quantity must be a whole number from 1 to 100')
    return int(number)


def validate_inventory(records):
    total=0
    for record in records:
        count=quantity(record)
        locations=record.get('instance_locations',[])
        if not isinstance(locations,list) or len(locations)>100 or any(not isinstance(x,str) or len(x)>120 for x in locations):
            raise ValueError(f'{record.get("tag")}: invalid physical unit locations')
        if record.get('status')!='VERIFIED':continue
        total+=count
        if record.get('quantity') in (None,'') and any(
                quantity({'quantity':c.get('values',{}).get('quantity')})>1 for c in record.get('candidates',[])):
            raise ValueError(f'{record.get("tag")}: review the source quantity before verifying')
        if count>1 and (len(locations)!=count or any(not x.strip() for x in locations)
                        or len({x.strip().upper() for x in locations})!=count):
            raise ValueError(f'{record.get("tag")}: enter one distinct room or location for each of its {count} physical units')
        if count==1 and len(locations)>1:
            raise ValueError(f'{record.get("tag")}: physical locations exceed the reviewed quantity')
    if total>500:raise ValueError('The report exceeds 500 physical equipment units')


def expand_instances(records):
    validate_inventory(records)
    expanded=[]
    for record in records:
        if record.get('status')!='VERIFIED':
            expanded.append(dict(record));continue
        for index in range(quantity(record)):
            unit=dict(record)
            unit['quantity']=1
            unit['instance_index']=index+1
            locations=record.get('instance_locations',[])
            if locations:unit['area_served']=locations[index].strip().upper()
            unit.pop('instance_locations',None)
            expanded.append(unit)
    return expanded
