#!/usr/bin/env python

import vdf
import sqlite3
import traceback
import time
import collections
from collections import defaultdict
import copy

CLASSES_USABLE = [ 'scout', 'soldier', 'pyro', 'demoman', 'heavy', 'engineer',
        'medic', 'sniper', 'spy' ]

class ItemParseError(Exception):
    def __init__(self, defindex):
        self.defindex = int(defindex)
        Exception.__init__(self, 'Item parsing error occurred at defindex {}'.format(defindex))

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
            dct[k] = copy.deepcopy(v)

def resolve_prefabs(item, prefabs):
    # generate list of prefabs
    prefab_list = item.get('prefab', '').split()
    for prefab in prefab_list:
        subprefabs = prefabs[prefab].get('prefab', '').split()
        prefab_list.extend(p for p in subprefabs if p not in prefab_list)
    
    # iterate over prefab list and merge, nested prefabs first
    # TODO make sure this is the same behavior the engine uses
    result = {}
    for prefab in ( prefabs[p] for p in reversed(prefab_list) ):
        dict_merge(result, prefab)
    
    dict_merge(result, item)
    return result, prefab_list

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

def main(items_game: str, database_file: str):
    '''
    Legacy interface for calling tf2idb.parse()
    (The new function call lets you pass in a database instead.)
    
    :param items_game:  Path to the items_game.txt file from TF2.
    :param database_file:  Path to a database file.  This file will be opened and closed in the
    process.
    '''
    with sqlite3.connect(database_file) as db:
        parse(items_game, db)

def parse(items_game: str, db: sqlite3.Connection, merge_allclass = True):
    """
    Parses items_game.txt into a database format usable by TF2IDB.
    
    :param items_game:  Path to the items_game.txt file from TF2.
    :param db:  An SQLite3 connection.
    :param merge_allclass:  Whether or not items designated as usable by every class should use
    the 'all' keyword.  Defaults to True.  Set to false if using a different branch of TF2IDB.
    """
    data = None
    with open(items_game) as f:
        data = vdf.parse(f)
        data = data['items_game']

    dbc = db.cursor()
    
    created_tables = {}
    
    def init_table(name: str, columns: list, primary_key = None):
        c = ', '.join(('"{}" {}'.format(k, v) for k, v in columns))
        
        if primary_key:
            column_names = (column for column, *_ in columns)
            if not all(key in column_names for key in primary_key):
                raise ValueError("Primary key not a valid column in table '{}'".format(name))
            c += ', PRIMARY KEY ({})'.format(', '.join( ('"{}"'.format(k)) for k in primary_key))
        
        query = 'CREATE TABLE "new_{}" ({})'.format(name, c)
        
        dbc.execute('DROP TABLE IF EXISTS new_{}'.format(name))
        dbc.execute(query)
        
        created_tables[name] = [ column for column, *_ in columns ]
    
    def insert_dict(name: str, item: dict, prop_remap: dict = {}):
        if not name in created_tables:
            raise ValueError("Table '{}' does not exist")
        
        dbc.execute('INSERT INTO new_{name} ({cols}) VALUES ({args})'.format(
                name = name,
                cols = ','.join(created_tables[name]),
                args = ','.join(':' + prop_remap.get(col, col) for col in created_tables[name])),
                item)

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
    ], primary_key = ('id', 'capability'))
    
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
    
    init_table('tf2idb_rarities', [
        ('name', 'TEXT PRIMARY KEY NOT NULL'),
        ('value', 'INTEGER NOT NULL')
    ])
    
    init_table('tf2idb_item_rarities', [
        ('id', 'INTEGER PRIMARY KEY NOT NULL'),
        ('rarity', 'INTEGER'),
        ('collection', 'TEXT')
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
        insert_dict('tf2idb_attributes', defaultdict(lambda: None, { **{ 'id': k }, **v }))

    # conflicts
    for k,v in data['equip_conflicts'].items():
        dbc.executemany('INSERT INTO new_tf2idb_equip_conflicts (name,region) VALUES (?,?)',
                ((k, region) for region in v.keys()))

    # rarities
    db.executemany('INSERT INTO new_tf2idb_rarities (name, value) VALUES (?, ?)',
            ((rname, rdata['value']) for rname, rdata in data['rarities'].items()))
    
    # item / rarity mapping
    item_rarity = {}
    for collection, collection_desc in data['item_collections'].items():
        for rarity, itemlist in collection_desc['items'].items():
            if rarity in data['rarities']:
                for item in itemlist:
                    item_rarity[item] = (collection, int(data['rarities'][rarity]['value']))
    
    # items
    item_defaults = {'propername': 0, 'item_quality': ''}
    
    for id,v in data['items'].items():
        if id == 'default':
            continue
        
        i, prefabs_used = resolve_prefabs(v, data['prefabs'])
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
            
            insert_dict('tf2idb_item',
                    defaultdict(lambda: None, { **item_defaults, **item_insert_values, **i }),
                    prop_remap = {'class': 'item_class', 'slot': 'item_slot', 'quality': 'item_quality'})

            default_slot = i.get('item_slot', None)
            used_classes = i.get('used_by_classes', {})
            if merge_allclass and all(c in used_classes for c in CLASSES_USABLE):
                # insert the 'all' keyword into tf2idb_class instead of a row for each class
                dbc.execute('INSERT INTO new_tf2idb_class (id, class, slot) VALUES (?, ?, ?)',
                        (id, 'all', default_slot))
            else:
                dbc.executemany('INSERT INTO new_tf2idb_class (id,class,slot) VALUES (?,?,?)',
                        ((id, prof.lower(), val if val != '1' else default_slot)
                        for prof, val in used_classes.items()))

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
            
            # item rarity
            if i['name'] in item_rarity:
                dbc.execute('INSERT INTO new_tf2idb_item_rarities (id, collection, rarity) VALUES (?, ?, ?)',
                        (id,) + item_rarity[ i['name'] ])
        except Exception as e:
            raise ItemParseError(id) from e

    # finalize tables
    for table in created_tables.keys():
        dbc.execute('DROP TABLE IF EXISTS %s' % table)
        dbc.execute('ALTER TABLE new_%s RENAME TO %s' % (table, table))

    db.commit()
    dbc.execute('VACUUM')

if __name__ == "__main__":
    import argparse, os
    parser = argparse.ArgumentParser(
            description="Parses the items_game file into a SQLite database.",
            usage='%(prog)s ITEMS DATABASE')

    parser.add_argument('items_game', metavar='ITEMS', help="path to items_game.txt")
    parser.add_argument('database', metavar='DATABASE', help="database to output to")

    args = parser.parse_args()

    if not os.path.isfile(args.items_game):
        raise ValueError("items_game.txt not found or is not a file")

    if not os.path.isfile(args.database) and os.path.exists(args.database):
        raise ValueError("missing output database or is not a file")

    main(args.items_game, args.database)
