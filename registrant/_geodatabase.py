'''
Geodatabase class representing an Esri geodatabase
'''
from __future__ import print_function
import os
from collections import OrderedDict, defaultdict

try:
    import arcpy
    arcpy_found = True
except:
    arcpy_found = False
    import ogr
    import json
    import xml.etree.ElementTree as ET

from ._data_objects import Table, TableOgr, FeatureClass, FeatureClassOgr
from ._util_mappings import (GDB_RELEASE, GDB_WKSPC_TYPE, GDB_PROPS, GDB_DOMAIN_PROPS,
                             GDB_TABLE_PROPS, GDB_FC_PROPS, OGR_GDB_DOMAIN_PROPS,
                             OGR_DOMAIN_PROPS_MAPPINGS)


########################################################################
class Geodatabase(object):
    """Geodatabase object"""

    def __init__(self, path):
        """Constructor"""
        self.path = path
        self.release = self._get_release()
        self.wkspc_type = self._get_wkspc_type()

    #----------------------------------------------------------------------
    def get_pretty_props(self):
        """get pretty properties as ordered dict"""
        od = OrderedDict()
        for k, v in GDB_PROPS.items():
            od[v] = self.__dict__[k]
        return od

    #----------------------------------------------------------------------
    def get_domains(self):
        """return geodatabase domains as ordered dict"""
        domains_props = []
        if arcpy_found:
            for domain in arcpy.da.ListDomains(self.path):
                od = OrderedDict()
                for k, v in GDB_DOMAIN_PROPS.items():
                    od[v] = getattr(domain, k, '')
                domains_props.append(od)
            return domains_props
        else:
            gdb_domains = self._ogr_get_domains()
            for domain_type, domains in gdb_domains.items():
                for domain in domains:
                    od = OrderedDict()
                    for k, v in OGR_GDB_DOMAIN_PROPS.items():
                        if k == 'domainType':
                            od[v] = OGR_DOMAIN_PROPS_MAPPINGS[domain_type]

                        #describing domain range
                        elif k == 'range':
                            try:
                                od[v] = (float(domain.find('MinValue').text),
                                         float(domain.find('MaxValue').text))
                            except AttributeError:
                                od[v] = ''

                        #describing domain coded values
                        elif k == 'codedValues':
                            try:
                                cvs = domain.find('CodedValues').findall('CodedValue')
                                od[v] = {
                                    cv.find('Code').text: cv.find('Name').text
                                    for cv in cvs
                                }
                            except AttributeError:
                                od[v] = ''
                        else:
                            try:
                                if domain.find(k).text:
                                    od[v] = OGR_DOMAIN_PROPS_MAPPINGS.get(
                                        domain.find(k).text, domain.find(k).text)
                                else:
                                    od[v] = ''
                            except AttributeError:
                                od[v] = ''

                    domains_props.append(od)
            return domains_props

    #----------------------------------------------------------------------
    def get_tables(self):
        """return geodatabase tables as Table class instances"""
        tables = []
        if arcpy_found:
            arcpy.env.workspace = self.path
            for tbl in arcpy.ListTables():
                try:
                    tbl_instance = Table(arcpy.Describe(tbl).catalogPath)
                    od = OrderedDict()
                    for k, v in GDB_TABLE_PROPS.items():
                        od[v] = getattr(tbl_instance, k, '')

                    #custom props
                    od['Row count'] = tbl_instance.get_row_count()
                    tables.append(od)
                except Exception as e:
                    print("Error. Could not read table", tbl, ". Reason: ", e)

        else:
            ds = ogr.Open(self.path, 0)
            table_names = [
                ds.GetLayerByIndex(i).GetName() for i in range(0, ds.GetLayerCount())
                if not ds.GetLayerByIndex(i).GetGeometryColumn()
            ]
            for table_name in table_names:
                try:
                    tbl_instance = TableOgr(self.path, table_name)
                    od = OrderedDict()
                    for k, v in GDB_TABLE_PROPS.items():
                        od[v] = getattr(tbl_instance, k, '')

                    #custom props
                    od['Row count'] = tbl_instance.get_row_count()
                    tables.append(od)
                except Exception as e:
                    print(e)
        return tables

    #----------------------------------------------------------------------
    def get_feature_classes(self):
        """return geodatabase feature classes as ordered dicts"""
        fcs = []
        if arcpy_found:
            arcpy.env.workspace = self.path
            #iterate feature classes within feature datasets
            fds = [fd for fd in arcpy.ListDatasets(feature_type='feature')]
            if fds:
                for fd in fds:
                    arcpy.env.workspace = os.path.join(self.path, fd)
                    for fc in arcpy.ListFeatureClasses():
                        fc_instance = FeatureClass(arcpy.Describe(fc).catalogPath)
                        od = OrderedDict()
                        for k, v in GDB_FC_PROPS.items():
                            od[v] = getattr(fc_instance, k, '')
                        #custom props
                        od['Row count'] = fc_instance.get_row_count()
                        od['Feature dataset'] = fd
                        fcs.append(od)

            #iterate feature classes in the geodatabase root
            arcpy.env.workspace = self.path
            for fc in arcpy.ListFeatureClasses():
                fc_instance = FeatureClass(arcpy.Describe(fc).catalogPath)
                od = OrderedDict()
                for k, v in GDB_FC_PROPS.items():
                    od[v] = getattr(fc_instance, k, '')
                #custom props
                od['Row count'] = fc_instance.get_row_count()
                od['Feature dataset'] = ''
                fcs.append(od)

        else:
            ds = ogr.Open(self.path, 0)
            fcs_names = [
                ds.GetLayerByIndex(i).GetName() for i in range(0, ds.GetLayerCount())
                if ds.GetLayerByIndex(i).GetGeometryColumn()
            ]
            for fc_name in fcs_names:
                try:
                    fc_instance = FeatureClassOgr(self.path, fc_name)
                    od = OrderedDict()
                    for k, v in GDB_FC_PROPS.items():
                        od[v] = getattr(fc_instance, k, '')
                    #custom props
                    od['Row count'] = fc_instance.get_row_count()
                    fcs.append(od)
                except Exception as e:
                    print(e)
        return fcs

    #----------------------------------------------------------------------
    def _ogr_get_gdb_metadata(self):
        """return an xml object with the geodatabase metadata"""
        ds = ogr.Open(self.path, 0)
        res = ds.ExecuteSQL('select * from GDB_Items')
        res.CommitTransaction()

        for i in xrange(0, res.GetFeatureCount()):
            item = json.loads(
                res.GetNextFeature().ExportToJson())['properties']['Definition']
            if item:
                xml = ET.fromstring(item)
                if xml.tag == 'DEWorkspace':
                    break
        del ds
        return xml

    #----------------------------------------------------------------------
    def _ogr_get_domains(self):
        """return an xml object with the geodatase domains metadata"""
        ds = ogr.Open(self.path, 0)
        res = ds.ExecuteSQL('select * from GDB_Items')
        res.CommitTransaction()

        domains = defaultdict(list)
        for i in xrange(0, res.GetFeatureCount()):
            item = json.loads(
                res.GetNextFeature().ExportToJson())['properties']['Definition']
            if item:
                xml = ET.fromstring(item)
                if xml.tag in ('GPCodedValueDomain2', 'GPRangeDomain2'):
                    domains[xml.tag].append(xml)
        del ds
        return domains

    #----------------------------------------------------------------------
    def _get_release(self):
        """return geodatabase release version"""
        if arcpy_found:
            return GDB_RELEASE.get(arcpy.Describe(self.path).release, '')
        else:
            xml = self._ogr_get_gdb_metadata()
            return GDB_RELEASE.get(','.join([
                xml.find('MajorVersion').text,
                xml.find('MinorVersion').text,
                xml.find('BugfixVersion').text
            ]), '')

    #----------------------------------------------------------------------
    def _get_wkspc_type(self):
        """return geodatabase workspace type - personal, file, SDE"""
        if arcpy_found:
            return [
                value for key, value in GDB_WKSPC_TYPE.items()
                if key.lower() in arcpy.Describe(
                    self.path).workspaceFactoryProgID.lower()
            ][0]
        else:
            return 'File geodatabase'