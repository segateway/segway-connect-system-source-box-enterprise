import json
import time
import asyncio
import orjson
import os

from boxsdk import Client, JWTAuth
from boxsdk.exception import BoxException
from boxsdk.object.events import EnterpriseEventsStreamType
import requests
import backoff

from syslogng import LogSource
from syslogng import LogMessage
from syslogng import Logger
from syslogng import Persist

logger = Logger()

config_path = os.environ.get("SEGWAY_BOX_SECRET_PATH", "")
MAX_CHUNK_SIZE: int = int(os.environ.get("SEGWAY_BOX_CHUNK_SIZE", "500"))


class EventStream(LogSource):
    """Provides a syslog-ng async source for Microsoft Event hub"""

    cancelled: bool = False
        
    def init(self, options):
        self._client = None
        self.auth()
        logger.info("Authentication complete")
        self.persist = Persist("EventStream", defaults={"stream_position": 0})
        logger.info(f"Resuming collection at stream_position={self.persist}")        
        return True
    
    def auth(self):
            path = os.path.join(config_path,'box.json')
            f = open(path)
            self.auth_dict = json.load(f)
            f.close()
            try:
                result=JWTAuth.from_settings_dictionary(self.auth_dict)
            except (TypeError, ValueError, KeyError):
                logger.error('Could not load JWT from settings dictionary')
                return False
            self._client = Client(result)

    
    def run(self):
        """Simple Run method to create the loop"""
        asyncio.run(self.receive_batch())

    async def receive_batch(self):
        params = {
                    'limit': MAX_CHUNK_SIZE,
                    'stream_type': EnterpriseEventsStreamType.ADMIN_LOGS,
                    'stream_position': self.persist['stream_position']
                }
        timeout=5
        while not self.cancelled:
            # self.cancelled = True
            # try:
            box_response = self._get_events(params)
            entries = box_response['entries']
            for entry in entries:
                event = EventStream.clean_event(entry)
                record_lmsg = LogMessage(orjson.dumps(event))
                self.post_message(record_lmsg)
                
            self.persist['stream_position'] = box_response['next_stream_position']
            params['stream_position']=box_response['next_stream_position']
            logger.info(f"Posted count={len(entries)} next_stream_position={params['stream_position']}")

    def backoff_hdlr_exp(details):
        logger.info("Backing off {wait:0.1f} seconds after {tries} tries "
            "with args {args}"
            .format(**details))
        
    def backoff_hdlr_pred(details):
        logger.info("Backing off {wait:0.1f} seconds after {tries} tries "
            "with args {args} result {value}"
            .format(**details))

                                        
    @backoff.on_exception(backoff.expo,
                    (requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError),max_time=300,on_backoff=backoff_hdlr_exp)
    @backoff.on_predicate(backoff.expo, lambda x: x['entries'] == [],max_time=300,on_backoff=backoff_hdlr_pred)
    def _get_events(self,params):
        box_response = self._client.make_request(
            'GET',
            self._client.get_url('events'),
            params=params,
            timeout=30
        )
        result = box_response.json()
        return result 
    
    

    @staticmethod
    def clean_event(source_dict: dict):
        """
        Delete keys with the value ``None``  or ```` (empty) string in a dictionary, recursively.
        Remove empty list and dict objects

        This alters the input so you may wish to ``copy`` the dict first.
        """
        # For Python 3, write `list(d.items())`; `d.items()` won’t work
        # For Python 2, write `d.items()`; `d.iteritems()` won’t work
        for key, value in list(source_dict.items()):
            if value is None:
                del source_dict[key]
            elif isinstance(value, str) and value in ("", "None", "none"):
                del source_dict[key]
            elif isinstance(value, str):
                if value.endswith("\n"):
                    value = value.strip("\n")

                if value.startswith('{"'):
                    try:
                        value = orjson.loads(value)
                        EventStream.clean_event(value)
                        source_dict[key] = value
                    except orjson.JSONDecodeError:
                        pass
            elif isinstance(value, dict) and not value:
                del source_dict[key]
            elif isinstance(value, dict):
                EventStream.clean_event(value)
            elif isinstance(value, list) and not value:
                del source_dict[key]
        return source_dict  # For convenience