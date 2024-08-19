class XPathError(BaseException):

  def __init__(self, msg: str, name: str, xpath: str, in_name: str = None, in_xpath: str = None):
    self.msg = msg
    self.name = name
    self.xpath = xpath
    self.in_name = in_name
    self.in_xpath = in_xpath
    super().__init__(self.msg)
  
  def __str__(self):
    return self.msg


class APIError(BaseException):

  def __init__(self, msg: str, name: str):
    self.msg = msg
    self.api = name
    super().__init__(self.msg)
  
  def __str__(self):
    return self.msg
  
  
class ActionError(BaseException):
  '''
  It' s unnecessary to record xpath, since it's already checked by XPathError
  '''
  def __init__(self, msg: str, name: str, xpath: str, action: str, target: str):
    self.msg = msg
    self.name = name
    self.xpath = xpath
    self.action = action
    self.target = target
    super().__init__(self.msg)
  
  def __str__(self):
    return self.msg
  
