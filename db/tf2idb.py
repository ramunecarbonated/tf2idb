#!/usr/bin/env python

import vdf
import sqlite3
import traceback
import time
import collections
from collections import defaultdict

class ItemParseError(Exception):
    def __init__(self, defindex):
        self.defindex = int(defindex)
        Exception.__init__(self, 'Item parsing error occurred at defindex {}'.format(defindex))

DATABASE_TABLES = [
    'tf2idb_class', 'tf2idb_item_attributes', 'tf2idb_item', 'tf2idb_particles',
    'tf2idb_equip_conflicts', 'tf2idb_equip_regions', 'tf2idb_capabilities',
    'tf2idb_attributes', 'tf2idb_qualities'
]

#https://gist.github.com/angstwad/bf22d1822c38a92ec0a9
def dict_merge(dct, merge_dct):
    """ Recursive dict merge. Inspired by :meth:``dict.update()``, instead of
    updating only top-level keys, dict_merge recurses down into dicts nested
    to an arbitrary depth, updating keys. The ``merge_dct`` is merged into
    ``dct``.
    :param dct: dict onto which the merge is executed
    :param merge_dct: dct merged into dct
    :return: None
    """
    for k, v in merge_dct.items():
        if (k == 'used_by_classes' or k == 'model_player_per_class'):    #handles Demoman vs demoman... Valve pls
            v = dict((k2.lower(), v2) for k2, v2 in v.items())
        if (k in dct and isinstance(dct[k], dict) and isinstance(v, collections.Mapping)):
            dict_merge(dct[k], v)
        else:
            if (callable(getattr(v, "copy", None))):
                dct[k] = v.copy()
            else:
                dct[k] = v

def resolve_prefabs(item, data):
    prefabs = item.get('prefab')
    prefab_aggregate = {}
    if prefabs:
        for prefab in prefabs.split():
            prefab_data = data['prefabs'][prefab].copy()
            prefab_data = resolve_prefabs(prefab_data, data)
            dict_merge(prefab_aggregate, prefab_data)
        dict_merge(prefab_aggregate, item)
    else:
        prefab_aggregate = item.copy()
    return prefab_aggregate

def item_has_australium_support(defindex: int, properties: dict):
    '''
    Returns True if the specified item seems to have australium support.
    '''
    banned_attrs = [ 'paintkit_proto_def_index', 'limited quantity item' ]
    banned_class = [ 'craft_item', '' ]
    banned_defindex = [ 482 ]
    
    if (properties.get('item_quality') == 'unique'
            and properties.get('craft_material_type') == 'weapon'
            and not defindex in banned_defindex
            and not properties.get('item_class') in banned_class
            and not any(attr in banned_attrs for attr in properties.get('static_attrs', {}))):
        return any(style.get('image_inventory', '').endswith('_gold')
                for _, style in properties.get('visuals', {}).get('styles', {}).items())
    return False

def item_has_paintkit_support(defindex: int, properties: dict):
    '''
    Returns True if the specified item seems to have paintkit support.
    '''
    return 'paintkit_base' in properties.get('prefab', '').split()

def main(items_game, database_file):
    data = None
    with open(items_game) as f:
        data = vdf.parse(f)
        data = data['items_game']

    db = sqlite3.connect(database_file)
    dbc = db.cursor()

    for table in DATABASE_TABLES:
        dbc.execute('DROP TABLE IF EXISTS new_{}'.format(table))
    
    def init_table(name: str, columns: list, primary_key = None):
        # validates table name and columns
        if not name in DATABASE_TABLES:
            raise ValueError("'{}' not a defined table; add it to the 'DATABASE_TABLES' list".format(name))
        
        c = ', '.join(('"{}" {}'.format(k, v) for k, v in columns))
        
        if primary_key:
            column_names = (column for column, *_ in columns)
            if not all(key in column_names for key in primary_key):
                raise ValueError("Primary key not a valid column in table '{}'".format(name))
            c += ', PRIMARY KEY ({})'.format(', '.join( ('"{}"'.format(k)) for k in primary_key))
        
        query = 'CREATE TABLE "new_{}" ({})'.format(name, c)
        dbc.execute(query)

    init_table('tf2idb_class', [
        ('id', 'INTEGER NOT NULL'), ('class', 'TEXT NOT NULL'), ('slot', 'TEXT')
    ], primary_key = ('id', 'class'))
    
    init_table('tf2idb_item_attributes', [
        ('id', 'INTEGER NOT NULL'), ('attribute', 'INTEGER NOT NULL'), ('value', 'TEXT NOT NULL'),
        ('static', 'INTEGER')
    ], primary_key = ('id', 'attribute'))
    
    init_table('tf2idb_item', [
        ('id', 'INTEGER PRIMARY KEY NOT NULL'),
        ('name', 'TEXT NOT NULL'),
        ('item_name', 'TEXT'),
        ('class', 'TEXT NOT NULL'),
        ('slot', 'TEXT'),
        ('quality', 'TEXT NOT NULL'),
        ('tool_type', 'TEXT'),
        ('min_ilevel', 'INTEGER'),
        ('max_ilevel', 'INTEGER'),
        ('baseitem', 'INTEGER'),
        ('holiday_restriction', 'TEXT'),
        ('has_string_attribute', 'INTEGER'),
        ('propername', 'INTEGER')
    ])
    
    init_table('tf2idb_particles', [
        ('id', 'INTEGER PRIMARY KEY NOT NULL'), ('name', 'TEXT NOT NULL'),
        ('type', 'TEXT NOT NULL')
    ])
    
    init_table('tf2idb_equip_conflicts', [
        ('name', 'TEXT NOT NULL'), ('region', 'TEXT NOT NULL'),
    ], primary_key = ('name', 'region'))
    
    init_table('tf2idb_equip_regions', [
        ('id', 'INTEGER NOT NULL'), ('region', 'TEXT NOT NULL')
    ], primary_key = ('id', 'region'))
    
    init_table('tf2idb_capabilities', [
        ('id', 'INTEGER NOT NULL'), ('capability', 'TEXT NOT NULL')
    ])
    
    init_table('tf2idb_attributes', [
        ('id', 'INTEGER PRIMARY KEY NOT NULL'),
        ('name', 'TEXT NOT NULL'),
        ('attribute_class', 'TEXT'),
        ('attribute_type', 'TEXT'),
        ('description_string', 'TEXT'),
        ('description_format', 'TEXT'),
        ('effect_type', 'TEXT'),
        ('hidden', 'INTEGER'),
        ('stored_as_integer', 'INTEGER'),
        ('armory_desc', 'TEXT'),
        ('is_set_bonus', 'INTEGER'),
        ('is_user_generated', 'INTEGER'),
        ('can_affect_recipe_component_name', 'INTEGER'),
        ('apply_tag_to_item_definition', 'TEXT')
    ])
    
    init_table('tf2idb_qualities', [
        ('name', 'TEXT PRIMARY KEY NOT NULL'),
        ('value', 'INTEGER NOT NULL')
    ])

    nonce = int(time.time())
    dbc.execute('CREATE INDEX "tf2idb_item_attributes_%i" ON "new_tf2idb_item_attributes" ("attribute" ASC)' % nonce)
    dbc.execute('CREATE INDEX "tf2idb_class_%i" ON "new_tf2idb_class" ("class" ASC)' % nonce)
    dbc.execute('CREATE INDEX "tf2idb_item_%i" ON "new_tf2idb_item" ("slot" ASC)' % nonce)

    # qualities
    dbc.executemany('INSERT INTO new_tf2idb_qualities (name, value) VALUES (?,?)',
            ((qname, qdata['value']) for qname, qdata in data['qualities'].items()))

    # particles
    for particle_type, particle_list in data['attribute_controlled_attached_particles'].items():
        dbc.executemany('INSERT INTO new_tf2idb_particles (id, name, type) VALUES (?,?,?)',
                ((id, property['system'], particle_type) for id, property in particle_list.items()))

    # attributes
    attribute_type = {}
    for k,v in data['attributes'].items():
        atype = v.get('attribute_type', 'integer' if v.get('stored_as_integer') else 'float')
        attribute_type[v['name'].lower()] = (k, atype)
        dbc.execute('INSERT INTO new_tf2idb_attributes '
            '(id,name,attribute_class,attribute_type,description_string,description_format,effect_type,hidden,stored_as_integer,armory_desc,is_set_bonus,'
                'is_user_generated,can_affect_recipe_component_name,apply_tag_to_item_definition) '
            'VALUES (:id, :name, :attribute_class, :attribute_type, :description_string, :description_format, :effect_type, :hidden, :stored_as_integer, :armory_desc, :is_set_bonus, :is_user_generated, :can_affect_recipe_component_name, :apply_tag_to_item_definition)',
            defaultdict(lambda: None, { **{ 'id': k }, **v })
        )

    # conflicts
    for k,v in data['equip_conflicts'].items():
        dbc.executemany('INSERT INTO new_tf2idb_equip_conflicts (name,region) VALUES (?,?)',
                ((k, region) for region in v.keys()))

    # items
    item_defaults = {'propername': 0, 'item_quality': ''}
    
    for id,v in data['items'].items():
        if id == 'default':
            continue
        i = resolve_prefabs(v, data)
        baseitem = 'baseitem' in i

        try:
            has_string_attribute = False
            for name,value in i.get('static_attrs', {}).items():
                aid,atype = attribute_type[name.lower()]
                if atype == 'string':
                    has_string_attribute = True
                dbc.execute('INSERT INTO new_tf2idb_item_attributes (id,attribute,value,static) VALUES (?,?,?,?)', (id,aid,value,1))

            for name,info in i.get('attributes', {}).items():
                aid,atype = attribute_type[name.lower()]
                if atype == 'string':
                    has_string_attribute = True
                dbc.execute('INSERT INTO new_tf2idb_item_attributes (id,attribute,value,static) VALUES (?,?,?,?)', (id,aid,info['value'],0))

            tool = i.get('tool', {}).get('type')
            item_insert_values = {
                'id': id, 'tool_type': tool, 'baseitem': baseitem, 'has_string_attribute': has_string_attribute
            }
            
            dbc.execute('INSERT INTO new_tf2idb_item '
                '(id,name,item_name,class,slot,quality,tool_type,min_ilevel,max_ilevel,baseitem,holiday_restriction,has_string_attribute,propername) '
                'VALUES (:id, :name, :item_name, :item_class, :item_slot, :item_quality, :tool_type, :min_ilevel, :max_ilevel, :baseitem, :holiday_restriction, :has_string_attribute, :propername)',
                defaultdict(lambda: None, { **item_defaults, **item_insert_values, **i })
            )

            dbc.executemany('INSERT INTO new_tf2idb_class (id,class,slot) VALUES (?,?,?)',
                    ((id, prof.lower(), val if val != '1' else None)
                    for prof, val in i.get('used_by_classes', {}).items()))

            region_field = i.get('equip_region') or i.get('equip_regions')
            if region_field:
                if type(region_field) is str:
                    region_field = {region_field: 1}
                dbc.executemany('INSERT INTO new_tf2idb_equip_regions (id,region) VALUES (?,?)',
                        ((id, region) for region in region_field.keys()))

            # capabilties
            dbc.executemany('INSERT INTO new_tf2idb_capabilities (id,capability) VALUES (?,?)',
                    ((id, (capability if val != '0' else '!'+capability))
                    for capability, val in i.get('capabilities', {}).items()))
            
            # custom extended capabilities
            if item_has_australium_support(int(id), i):
                dbc.execute('INSERT INTO new_tf2idb_capabilities (id, capability) VALUES (?, ?)',
                        (id, 'supports_australium'))
            if item_has_paintkit_support(int(id), i):
                dbc.execute('INSERT INTO new_tf2idb_capabilities (id, capability) VALUES (?, ?)',
                        (id, 'can_apply_paintkit'))
        except Exception as e:
            raise ItemParseError(id) from e

    # finalize tables
    for table in DATABASE_TABLES:
        dbc.execute('DROP TABLE IF EXISTS %s' % table)
        dbc.execute('ALTER TABLE new_%s RENAME TO %s' % (table, table))

    db.commit()
    dbc.execute('VACUUM')
    db.close()

if __name__ == "__main__":
    import argparse, os
    parser = argparse.ArgumentParser(
            description="Parses the items_game file into a SQLite database.",
            usage='%(prog)s ITEMS DATABASE')

    parser.add_argument('items_game', metavar='ITEMS', help="path to items_game.txt")
    parser.add_argument('database', metavar='DATABASE', help="database to output to")

    args = parser.parse_args()

    if not os.path.exists(args.items_game) or os.path.isdir(args.items_game):
        raise ValueError("items_game.txt not found or is not a file")

    if not os.path.isfile(args.database):
        raise ValueError("missing output database or is not a file")

    main(args.items_game, args.database)
