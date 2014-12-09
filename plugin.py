from __future__ import (absolute_import, division, print_function)
# NOTE: unicode_literals removed from __future__ due to issues with cherrypy
import logging
import time
import sys
import cherrypy
import pprint
import json

import boundary_plugin
import boundary_accumulator


class BrixbitsApp(object):
    def __init__(self, data_callback, port=12001, username='brixbits', password='brixbits'):
        self.data_callback = data_callback

        self.port = port
        self.conf = {
            '/': {
                'tools.auth_basic.on': True,
                'tools.auth_basic.realm': 'Brixbitz Agent',
                'tools.auth_basic.checkpassword': lambda self, u, p: u == username and p == password,
            }
        }

    def start(self):
        cherrypy.config.update({'server.socket_port': self.port, 'server.socket_host': '0.0.0.0', 'log.screen': False})
        cherrypy.log.error_log.propagate = False
        cherrypy.log.access_log.propagate = False
        cherrypy.quickstart(self, '/', self.conf)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=('POST',))
    def put(self):
        len = cherrypy.request.headers['Content-Length']
        rawbody = cherrypy.request.body.read(int(len))
        data = json.loads(rawbody)
        self.data_callback(data)
        return 'OK'


class BrixbitsPlugin(object):
    MESSAGE_TYPE_APP_SERVER_METRICS = 2
    MESSAGE_TYPE_TRANSACTION_METRICS = 3

    def __init__(self, boundary_metric_prefix):
        self.boundary_metric_prefix = boundary_metric_prefix
        self.settings = boundary_plugin.parse_params()
        self.accumulator = boundary_accumulator
        self.listener_app = None

    @staticmethod
    def get_app_server_metric_list():
        return (
            ('BRIXBITS_POC_PERCENT_HEAP_MEMORY', 'CurrentPctOfHeapMemoryInUse', False),
            ('BRIXBITS_POC_ERRORS', 'DeltaErrors', True),
            ('BRIXBITS_POC_EXCEPTIONS', 'DeltaExceptions', True),
            ('BRIXBITS_POC_GC_COUNT', 'DeltaGarbageCollectionCount', False),
            ('BRIXBITS_POC_GC_PERCENT_CPU', 'DeltaGarbageCollectionPctCPU', False),
            ('BRIXBITS_POC_GC_TIME', 'DeltaGarbageCollectionTime', False),
            ('BRIXBITS_POC_JVM_CPU_INSTANCES_EXCEEDED', 'DeltaJVMCPUInstancesExceeded', False),
            ('BRIXBITS_POC_JVM_CPU_INSTANCES_EXCEEDED_PERCENT', 'DeltaJVMCPUInstancesExceededPct', False),
            ('BRIXBITS_POC_LIVE_SESSIONS', 'DeltaLiveSessions', False),
            ('BRIXBITS_POC_NEW_SESSIONS', 'DeltaNewSessions', False),
            ('BRIXBITS_POC_TRANSACTIONS', 'DeltaTransactions', False),
            ('BRIXBITS_POC_EXCEEDED_INSTANCE_LATENCY', 'ExceededInstanceLatency', True),
            ('BRIXBITS_POC_EXCEEDED_INTERVAL_LATENCY', 'ExceededIntervalLatency', True),
            ('BRIXBITS_POC_AVG_JVM_CPU_USED', 'IntervalAvgJVMCPUUsed', False),
        )

    @staticmethod
    def get_transaction_metric_list():
        return (
            ('BRIXBITS_POC_ERRORS', 'DeltaErrors', True),
            ('BRIXBITS_POC_PERCENT_ERRORS', 'DeltaErrorsPct', False),
            ('BRIXBITS_POC_EXCEPTIONS', 'DeltaExceptions', True),
            ('BRIXBITS_POC_PERCENT_EXCEPTIONS', 'DeltaExceptionsPct', False),
            ('BRIXBITS_POC_TRANSACTIONS', 'DeltaTransactions', False),
            ('BRIXBITS_POC_EXCEEDED_INSTANCE_LATENCY', 'ExceededInstanceLatencyInterval', False),
            ('BRIXBITS_POC_EXCEEDED_INTERVAL_LATENCY', 'ExceededIntervalLatency', True),
            ('BRIXBITS_POC_LATENCY', 'IntervalLatency', False)
        )

    def handle_metric_list(self, metric_list, data, source):
        for metric_item in metric_list:
            boundary_name, metric_name, accumulate = metric_item[:3]
            metric_data = data.get(metric_name, None)
            if not metric_data:
                # If certain metrics do not exist or have no value
                # (e.g. disabled in the server or just inactive) - skip them.
                continue
            if accumulate:
                value = self.accumulator.accumulate(source + '_' + metric_name, float(metric_data))
            else:
                value = metric_data
            boundary_plugin.boundary_report_metric(self.boundary_metric_prefix + boundary_name, value, source)

    def handle_metrics(self, data):
        if int(data['msgType']) == self.MESSAGE_TYPE_APP_SERVER_METRICS:
            source = '%s_%s' % (data['Host'], data['AppInstance'])
            self.handle_metric_list(self.get_app_server_metric_list(), data['data'][0], source)
        elif int(data['msgType']) == self.MESSAGE_TYPE_TRANSACTION_METRICS:
            metric_list = self.get_transaction_metric_list()
            for trx in data['data']:
                source = '%s_%s_%s' % (data['Host'], data['AppInstance'], trx['TransactionName'])
                self.handle_metric_list(metric_list, trx, source)

    def main(self):
        logging.basicConfig(level=logging.ERROR, filename=self.settings.get('log_file', None))
        reports_log = self.settings.get('report_log_file', None)
        if reports_log:
            boundary_plugin.log_metrics_to_file(reports_log)
        boundary_plugin.start_keepalive_subprocess()

        self.listener_app = BrixbitsApp(self.handle_metrics, int(self.settings.get('port', 12001)),
            self.settings.get('username', 'brixbits'), self.settings.get('password', 'brixbits'))
        self.listener_app.start()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '-v':
        logging.basicConfig(level=logging.INFO)

    plugin = BrixbitsPlugin('')
    plugin.main()
