class XPathError(Exception): 

  def __init__(self, msg: str, name: str, xpath: str):
    self.msg = msg
    self.name = name
    self.xpath = xpath
    super().__init__(self.msg)
  
  def __str__(self):
    return self.msg


class APIError(Exception):

  def __init__(self, msg: str, name: str):
    self.msg = msg
    self.api = name
    super().__init__(self.msg)
  
  def __str__(self):
    return self.msg
  
  
class ActionError(Exception):
  '''
  It' s unnecessary to record xpath, since it's already checked by XPathError
  '''
  ACTION_MAP = {
    'touch': 'tap',
    'long_touch': 'long_tap'
  }
  def __init__(self, msg: str, name: str, xpath: str, action: str, target: str):
    self.msg = msg.replace(action, self.ACTION_MAP.get(action, action))
    self.name = name
    self.xpath = xpath
    self.action = action
    self.target = target
    super().__init__(self.msg)
  
  def __str__(self):
    return self.msg


class NotFoundError(Exception):

  def __init__(self, msg: str, name: str, xpath: str, group_name: str=None, group_xpath: str=None):
    self.msg = msg
    self.name = name
    self.xpath = xpath
    self.group_name = group_name
    self.group_xpath = group_xpath
    super().__init__(self.msg)
  
  def __str__(self):
    return self.msg
