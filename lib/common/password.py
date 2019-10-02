import requests
import configparser
from db.crypto import Crypto, CryptoPMP
from common.password_info import PasswordInfo

def decrypt_code(encrypted):
    crypto = Crypto()
    return crypto.decrypt(encrypted)


def get_password_by_auth_token(username, meta={}, api_pmp_str=None, auth_token=None, token_encrypted=True):
    if not api_pmp_str:
        api_pmp_str = meta['api_pmp_str']
    if not auth_token:
        auth_token = meta['db_conn_token']
    if token_encrypted:
        auth_token = decrypt_code(auth_token)
    request_url = "{}/user/{}/password?authToken={}".format(api_pmp_str, username, auth_token)
    faded_url = request_url.replace(auth_token, 'xxxxx')
    print('Token faded URL:', faded_url)
    response = requests.get(request_url)
    if response.status_code != 200:
        raise ValueError("PMP service is currently not available.", faded_url)
    response_body = response.json()
    if response_body["status"].lower() == "success":
        return PasswordInfo().set_password(username, CryptoPMP(meta=meta).decrypt(response_body["data"]))
    else:
        raise KeyError('Unable to get the password for {}, PMPStatus="{}", message="{}"'.format(username, response_body["status"], response_body["message"]))

        
def get_password(username, meta={}, api_pmp_str=None, auth_token=None, token_encrypted=True):
    pi = PasswordInfo()
    password = pi.get_password(username)
    return password if password else get_password_by_auth_token(username, meta, api_pmp_str, auth_token, token_encrypted)

    
if __name__ == '__main__':
    CONFIG_FILE = '../../config/config.properties'
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    meta = config['DEFAULT']
    print(get_password(username='devIrisRedis', meta=meta)) # get from PMP
    print(get_password(username='devIrisRedis', meta=meta)) # get from PasswordInfo
    print(get_password(username='devIrisMQ', api_pmp_str='http://engv3dstr2.eng.rsicorp.local/pmp',
                       meta=meta, auth_token='/qNhh30x3Pdy3SZP+cy0hNJ5vbFfwc6qW8+WXlwuJLUqh6DQvxTjTw=='))
    print(get_password(username='devIrisMQ', api_pmp_str='http://engv3dstr2.eng.rsicorp.local/pmp',
                       meta=meta, auth_token='/qNhh30x3Pdy3SZP+cy0hNJ5vbFfwc6qW8+WXlwuJLUqh6DQvxTjTw=='))

    print(get_password(username='admin', meta=meta)) # not a valid username

