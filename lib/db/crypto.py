
class Crypto:
    from Crypto.Cipher import DES
    from base64 import b64encode

    # convert base64 string to bytes
    def base64ToBytes(self, b64_string):
        from base64 import b64decode
        return b64decode(b64_string)

    #  convert string to base64
    def stringToBase64(self, input_string):
        from base64 import b64encode
        return b64encode(input_string)

    # returns the hash digest using MD5(used for key and iv generation)
    def PBEWithMD5AndDES(self):
        from Crypto.Hash import MD5
        password = b"cfgmgmt"
        salt = bytes([169, 155, 200, 50, 86, 53, 227, 3])
        result = password+salt
        # generate the digest
        for i in range(1, 11):
            hash_object = MD5.new()
            hash_object.update(result)
            result = hash_object.digest()
        # get the DES object using the result[0:8] as key and result[8:16] as iv
        return result

    # adding padding bits to the input string
    def pkcs7_padding(self, code):
        padding_bits = 8-(len(code) % 8)
        padding_text = ''
        padding_text += chr(padding_bits)*padding_bits
        return padding_text

    # encrypts the input message
    def encrypt(self, crypto_string):
        from Crypto.Cipher import DES
        # generates the hash digest
        hash_digest = self.PBEWithMD5AndDES()
        padded_text = self.pkcs7_padding(crypto_string)
        padded_input = bytes(crypto_string, 'utf-8') + bytes(padded_text, 'utf-8')
        encoder = DES.new(hash_digest[:8], DES.MODE_CBC, hash_digest[8:16])
        encrypter = encoder.encrypt(padded_input)
        return self.stringToBase64(encrypter)

    # Decryption
    def decrypt(self, crypto_string):
        from Crypto.Cipher import DES
        # returns the hash digest
        result = self.PBEWithMD5AndDES()
        decoder = DES.new(result[:8], DES.MODE_CBC, result[8:16])
        decrypted = decoder.decrypt(self.base64ToBytes(crypto_string)).decode('ascii')
        last = ord(decrypted[-1])
        if 0 < last < 9:
            return decrypted[:-last]
        else:
            return decrypted


class CryptoPMP(Crypto):
    def __init__(self, meta={}):
        self.meta = meta

    # returns the hash digest using MD5(used for key and iv generation)
    def PMPPBEWithMD5AndDES(self):
        from Crypto.Hash import MD5
        password = bytes(super().decrypt(self.meta["decrypt_key"]), 'ascii')
        salt = bytes([169, 155, 200, 50, 86, 53, 227, 3])
        result = password+salt
        # generate the digest
        for i in range(1, 11):
            hash_object = MD5.new()
            hash_object.update(result)
            result = hash_object.digest()
        # get the DES object using the result[0:8] as key and result[8:16] as iv
        return result

    def decrypt(self, crypto_string):
        from Crypto.Cipher import DES
        # returns the hash digest
        result = self.PMPPBEWithMD5AndDES()
        decoder = DES.new(result[:8], DES.MODE_CBC, result[8:16])
        decrypted = decoder.decrypt(self.base64ToBytes(crypto_string)).decode('ascii')
        last = ord(decrypted[-1])
        if 0 < last < 9:
            return decrypted[:-last]
        else:
            return decrypted


if __name__ == '__main__':
    print(Crypto().encrypt("Xn2r5u8x"))
    print(Crypto().decrypt("TUFqdJX5hqV9UcgMe43iLA=="))
    print(CryptoPMP(meta={"decrypt_key": "TUFqdJX5hqV9UcgMe43iLA=="}).decrypt("TM4H7ywreQaOkJYPW/xOEA=="))
