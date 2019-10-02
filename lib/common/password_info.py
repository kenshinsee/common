from common.singleton import SingletonMetaClass

class PasswordInfo(metaclass=SingletonMetaClass):

    def __init__(self):
        self.password_info = {}        
        
    def set_password(self, username, password):
        self.password_info[username] = password
        return self.password_info[username]
        
    def get_password(self, username=None):
        if username is None:
            return self.password_info
        elif username in self.password_info:
            return self.password_info[username]
        else:
            return None
    
    
if __name__=='__main__':
    
    pi = PasswordInfo()
    pi.set_password('mypass1', '111')
    pi.set_password('mypass2', '222')
    print(pi.get_password('mypass1'))
    
    pi1 = PasswordInfo()
    pi1.set_password('mypass1', '333')
    print(pi.get_password('mypass1'))
    print(pi1.get_password('mypass1'))
    print(pi1.get_password())
    
    
    