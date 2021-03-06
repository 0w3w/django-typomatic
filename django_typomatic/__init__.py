import re
import logging
from rest_framework import serializers
from .mappings import mappings

_LOG = logging.getLogger(f"django-typomatic.{__name__}")

# Serializers
__serializers = dict()
# Custom serializers.Field to TS Type mappings
__field_mappings = dict()
# Custom field_name to TS Type overrides
__mapping_overrides = dict()
# Default/Shared context
__default_context = 'default'

def ts_field(ts_type: str, context=__default_context):
    '''
    Any valid Django Rest Framework Serializer Field with this class decorator will
    be added to a list in a __field_mappings dictionary.
    Useful to define the type mapping of custom serializer Fields.
    e.g.
    @ts_field('string')
    class CustomFieldField(serializers.Field):
        def to_internal_value(self, data):
            pass
        def to_representation(self, obj):
            pass
    '''
    def decorator(cls):
        if issubclass(cls, serializers.Field):
            if context not in __field_mappings:
                __field_mappings[context] = dict()
            if cls not in __field_mappings[context]:
                __field_mappings[context][cls] = ts_type
        return cls
    return decorator

def ts_interface(context='default', mapping_overrides=None):
    '''
    Any valid Django Rest Framework Serializers with this class decorator will
    be added to a list in a dictionary.
    Optional parameters:
    'context': Will create separate dictionary keys per context.
        Otherwise, all values will be inserted into a list with a key of 'default'.
    'mapping_overrides': Dictionary of field_names to TS types
        Useful to properly serialize ModelSerializer runtime properties and ReadOnlyFields.
    e.g.
    @ts_interface(context='internal', mapping_overrides={"baz" : "string[]"})
    class Foo(serializers.Serializer):
        bar = serializer.IntegerField()
        baz = serializer.ReadOnlyField(source='baz_property')
    '''
    def decorator(cls):
        if issubclass(cls, serializers.Serializer):
            if context not in __serializers:
                __serializers[context] = []
            __serializers[context].append(cls)
            if mapping_overrides:
                if context not in __mapping_overrides:
                    __mapping_overrides[context] = dict()
                if cls not in __mapping_overrides[context]:
                    __mapping_overrides[context][cls] = mapping_overrides
        return cls
    return decorator

def __get_interface_name(name, prefix, suffix):
    name = re.sub('Serializer$', '', name)
    return f"{prefix}{name}{suffix}"

def __process_field(field_name, field, context, serializer, prefix, suffix):
    '''
    Generates and returns a tuple representing the Typescript field name and Type.
    '''
    is_many = hasattr(field, 'child')
    field_type = is_many and type(field.child) or type(field)
    if field_type in __serializers[context]:
        ts_type = __get_interface_name(field_type.__name__, prefix, suffix)
    elif (__default_context in __serializers) and field_type in __serializers[__default_context]:
        ts_type = __get_interface_name(field_type.__name__, prefix, suffix)
    elif (context in __field_mappings) and field_type in __field_mappings[context]:
        ts_type = __field_mappings[context].get(field_type, 'any')
    elif (__default_context in __field_mappings) and field_type in __field_mappings[__default_context]:
        ts_type = __field_mappings[__default_context].get(field_type, 'any')
    elif (context in __mapping_overrides) and (serializer in __mapping_overrides[context]) and field_name in __mapping_overrides[context][serializer]:
        ts_type = __mapping_overrides[context][serializer].get(field_name, 'any')
    else:
        ts_type = mappings.get(field_type, 'any')

    if is_many:
        ts_type += '[]'
    return (field_name, ts_type)

def __get_ts_interface(serializer, context, ts_interface_prefix, ts_interface_suffix):
    '''
    Generates and returns a Typescript Interface by iterating
    through the serializer fields of the DRF Serializer class
    passed in as a parameter, and mapping them to the appropriate Typescript
    data type.
    '''
    name = serializer.__name__
    _LOG.debug(f"Creating interface for {name}")
    fields = []
    if issubclass(serializer, serializers.ModelSerializer):
        instance = serializer()
        fields = instance.get_fields().items()
    else:
        fields = serializer._declared_fields.items()
    ts_fields = []
    ts_indexable_types = []
    for key, value in fields:
        ts_field = __process_field(key, value, context, serializer, ts_interface_prefix, ts_interface_suffix)
        ts_fields.append(f"    {ts_field[0]}: {ts_field[1]};")
        if ts_field[1] not in ts_indexable_types:
            ts_indexable_types.append(ts_field[1])
    collapsed_fields = '\n'.join(ts_fields)
    ts_indexable_type = ' | '.join(ts_indexable_types)
    name = __get_interface_name(name, ts_interface_prefix, ts_interface_suffix)
    indexable_type_str = f'    [x: string]: {ts_indexable_type};'
    return f'  export interface {name} {{\n{indexable_type_str}\n{collapsed_fields}\n  }}\n\n'

def generate_ts(output_path, context='default', ts_interface_prefix='', ts_interface_suffix='', all_contexts=False):
    '''
    When this function is called, a Typescript interface will be generated
    for each DRF Serializer in the serializers dictionary, depending on the
    optional context parameter provided. If the parameter is ignored, all
    serializers in the default value, 'default' will be iterated over and a
    list of Typescript interfaces will be returned via a list comprehension.

    The Typescript interfaces will then be outputted to the file provided.
    '''
    with open(output_path, 'w') as output_file:
        for declared_context in __serializers:
            if all_contexts or context == declared_context:
                interfaces = [__get_ts_interface(serializer, declared_context, ts_interface_prefix, ts_interface_suffix) for serializer in __serializers[declared_context]]
                output_file.write(f'\ndeclare namespace {declared_context} {{\n\n')
                output_file.write(''.join(interfaces))
                output_file.write('}')
