#!/usr/bin/env python3

"""
This is a NodeServer for August written by automationgeek (Jean-Francois Tremblay)
based on the NodeServer template for Polyglot v2 written in Python2/3 by Einstein.42 (James Milne) milne.james@gmail.com
"""

import polyinterface
import hashlib
import uuid
import time
import json
import sys
import ast
from copy import deepcopy
from august.api import Api 
from august.authenticator import Authenticator, AuthenticationState, ValidationResult
from august.lock import LockDetail, LockDoorStatus, LockStatus


LOGGER = polyinterface.LOGGER
SERVERDATA = json.load(open('server.json'))
VERSION = SERVERDATA['credits'][0]['version']

def get_profile_info(logger):
    pvf = 'profile/version.txt'
    try:
        with open(pvf) as f:
            pv = f.read().replace('\n', '')
    except Exception as err:
        logger.error('get_profile_info: failed to read  file {0}: {1}'.format(pvf,err), exc_info=True)
        pv = 0
    f.close()
    return { 'version': pv }

class Controller(polyinterface.Controller):

    def __init__(self, polyglot):
        super(Controller, self).__init__(polyglot)
        self.name = 'August'
        self.queryON = False
        self.email = ""
        self.password = ""
        self.install_id = ""
        self.userDict = ""
        self.hb = 0
        self.api = None
        self.authenticator = None
        self.authentication = None
        self.userDictEnable = False

    def start(self):
        LOGGER.info('Started August for v2 NodeServer version %s', str(VERSION))
        self.setDriver('ST', 1)
        try:
            if 'email' in self.polyConfig['customParams']:
                self.email = self.polyConfig['customParams']['email']
            else:
                self.email = "mlf@fineberg.org"
                
            if 'password' in self.polyConfig['customParams']:
                self.password = self.polyConfig['customParams']['password']
            else:
                self.password = "g0612Uaq812W71!"
            
            # Generate a UUID ( 11111111-1111-1111-1111-111111111111 )
            if 'install_id' in self.polyConfig['customParams']:
                self.install_id = self.polyConfig['customParams']['install_id']
            else:
                self.install_id = str(uuid.uuid4())
                self.saveCustomData({ 'install_id': self.install_id })
                LOGGER.debug('UUID Generated: {}'.format(self.install_id))

            if 'tokenFilePath' in self.polyConfig['customParams']:
                self.tokenFilePath = self.polyConfig['customParams']['tokenFilePath']
            else:
                self.tokenFilePath = ""
            
            # {'John Doe': 1, 'Paul Doe':2}
            if 'userDict' in self.polyConfig['customParams']:
                self.userDict = self.polyConfig['customParams']['userDict']
                self.userDictEnable = True
            else:
                self.userDict = "{'None': 0}"
            
            if self.email == "" or self.password == "" or self.tokenFilePath == "":
                LOGGER.error('August requires email,password,tokenFilePath parameters to be specified in custom configuration.')
                return False
            else:
                self.check_profile()
                self.discover()

        except Exception as ex:
            LOGGER.error('Error starting August NodeServer: %s', str(ex))
    
    def query(self):
        for node in self.nodes:
            self.nodes[node].reportDrivers()
    
    def shortPoll(self):
        self.setDriver('ST', 1)
        for node in self.nodes:
            if  self.nodes[node].queryON == True :
                self.nodes[node].update()

    def longPoll(self):
        self.heartbeat()
        
        # Refresh Token
        self.authenticator.refresh_access_token()

    def heartbeat(self):
        LOGGER.debug('heartbeat: hb={}'.format(self.hb))
        if self.hb == 0:
            self.reportCmd("DON",2)
            self.hb = 1
        else:
            self.reportCmd("DOF",2)
            self.hb = 0

    def discover(self, *args, **kwargs):
        count = 1
        
        self.api = Api(timeout=20)
        self.authenticator = Authenticator(self.api, "email", self.email, self.password, install_id=self.install_id, access_token_cache_file=self.tokenFilePath)
        self.authentication = self.authenticator.authenticate()
        if ( self.authentication.state is AuthenticationState.AUTHENTICATED ) :
            locks = self.api.get_locks(self.authentication.access_token)
            for lock in locks:
                myhash =  str(int(hashlib.md5(lock.device_id.encode('utf8')).hexdigest(), 16) % (10 ** 8))
                self.addNode(AugustLock(self,self.address,myhash,  "lock_" + str(count),self.api, self.authentication, lock ))
                count = count + 1
        else :
            self.authenticator.send_verification_code()
            LOGGER.error('August requires validation, please send your authentification code')
        
    def delete(self):
        LOGGER.info('Deleting August')

    def check_profile(self):
        self.profile_info = get_profile_info(LOGGER)
        # Set Default profile version if not Found
        cdata = deepcopy(self.polyConfig['customData'])
        LOGGER.info('check_profile: profile_info={0} customData={1}'.format(self.profile_info,cdata))
        if not 'profile_info' in cdata:
            cdata['profile_info'] = { 'version': 0 }
        if self.profile_info['version'] == cdata['profile_info']['version']:
            self.update_profile = False
        else:
            self.update_profile = True
            self.poly.installprofile()
        LOGGER.info('check_profile: update_profile={}'.format(self.update_profile))
        cdata['profile_info'] = self.profile_info
        self.saveCustomData(cdata)

    def install_profile(self,command):
        LOGGER.info("install_profile:")
        self.poly.installprofile()
        
    def send_validation_code(self,command) :
        LOGGER.info("Send Validation Code")
        val = int(command.get('value'))
        validation_result = self.authenticator.validate_verification_code(val)
        
        if ( validation_result is ValidationResult.INVALID_VERIFICATION_CODE ) :
            LOGGER.info("Invalid Verification Code : %s", str(val) )
            
        self.authentication = self.authenticator.authenticate()
        if ( self.authentication.state is not AuthenticationState.AUTHENTICATED ) :
            LOGGER.info("Invalid Authentication Code")
        else :
            LOGGER.info("Successfully Authentificated")

    id = 'controller'
    commands = {
        'QUERY': query,
        'DISCOVER': discover,
        'INSTALL_PROFILE': install_profile,
        'VALIDATE_CODE': send_validation_code,
    }
    drivers = [{'driver': 'ST', 'value': 1, 'uom': 2}, 
               {'driver': 'GV3', 'value': 0, 'uom': 56}]

class AugustLock(polyinterface.Node):

    def __init__(self, controller, primary, address, name, api, authentication, lock):

        super(AugustLock, self).__init__(controller, primary, address, name)
        self.queryON = True
        self.api = api
        self.authentication = authentication
        self.lock = lock
        self.userDictEnable = self.parent.userDictEnable
        self.userDict = ast.literal_eval(self.parent.userDict)

    def start(self):
        self.setDriver('GV2', 101)
        self.setDriver('GV4', 101)

    def setOn(self, command):
        self.api.lock(self.authentication.access_token,self.lock.device_id)
        self.setDriver('GV2', 100)
        self.reportCmd('LOCK')
        
    def setOff(self, command):
        self.api.unlock(self.authentication.access_token,self.lock.device_id)
        self.setDriver('GV2', 0)
        self.reportCmd('UNLOCK')
    
    def query(self):
        self.reportDrivers()
    
    def update(self):
        try :
            if self.api.get_lock_status(self.authentication.access_token,self.lock.device_id) is LockStatus.UNLOCKED :
                self.setDriver('GV2', 0) 
            elif self.api.get_lock_status(self.authentication.access_token,self.lock.device_id) is LockStatus.LOCKED :
                self.setDriver('GV2', 100) 
            else :
                self.setDriver('GV2', 101) 

            battlevel = self.api.get_lock_detail(self.authentication.access_token,self.lock.device_id).battery_level
            self.setDriver('GV1', int(battlevel))
            
            doorStatus = self.api.get_lock_door_status(self.authentication.access_token,self.lock.device_id)
            if doorStatus is LockDoorStatus.OPEN :
                self.setDriver('GV4', 0)
            elif doorStatus is LockDoorStatus.CLOSED :
                self.setDriver('GV4', 100)
            else :
                self.setDriver('GV4', 101)

            if ( self.userDictEnable ) :
                lastUser = self.api.get_house_activities(self.authentication.access_token,self.lock.house_id)[0].operated_by
                val = 0 
                for key in self.userDict  :
                    if key == lastUser :
                        val = self.userDict[key]
                self.setDriver('GV5',val)
            
        except Exception as ex:
            LOGGER.error('query: %s', str(ex))
            self.setDriver('GV1', 0)
            self.setDriver('GV2', 101)
            self.setDriver('GV4', 101)

    drivers = [{'driver': 'GV2', 'value': 100, 'uom': 11},
               {'driver': 'GV1', 'value': 0, 'uom': 51},
               {'driver': 'GV4', 'value': 100, 'uom': 79},
               {'driver': 'GV5', 'value': 0, 'uom': 56}]

    id = 'AUGUST_LOCK'
    commands = {
                    'LOCK': setOn,
                    'UNLOCK': setOff
                }

if __name__ == "__main__":
    try:
        polyglot = polyinterface.Interface('AugustNodeServer')
        polyglot.start()
        control = Controller(polyglot)
        control.runForever()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
