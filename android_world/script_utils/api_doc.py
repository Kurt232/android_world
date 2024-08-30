import json
import re
import datetime

from lxml import etree
from android_world.agents.agent_utils import HTMLSkeleton
from android_world.agents import agent_utils
from android_world.env import interface

class DependentAction():

  def __init__(self, action: str):
    '''
    still remember to consider back() action
    '''
    action = action.strip()
    self.raw_action: str = action
    self.screen_name: str = None
    self.api_name: str = None
    self.action_type: str = None
    self.argv: list[str] = None
    self.text: str = None

    # screen_name
    m = re.search(r'(\w+)__', action) # only first is screen name
    assert m is not None
    self.screen_name = m.group(1)
    _action = action[:m.start()] + action[m.end():]

    # argv
    self.argv = self._extract_arguments(_action)
    if len(self.argv) > 0:
      self.api_name = self.argv[0]
      self.name = self.screen_name + '__' + self.api_name

    # action_type
    if _action.startswith('tap'):
      self.action_type = 'touch'
      assert len(self.argv) == 1
    elif _action.startswith('long_tap'):
      self.action_type = 'long_touch'
      assert len(self.argv) == 1
    elif _action.startswith('set_text'):
      self.action_type = 'set_text'
      assert len(self.argv) == 2
      self.text = self.argv[1].strip("\'\"")
    elif _action.startswith('scroll'):
      self.action_type = 'scroll'
      assert len(self.argv) == 2
      direction = self.argv[1].strip("\'\"").lower()
      assert direction in ['up', 'down', 'left', 'right']
      self.action_type = 'scroll' + ' ' + direction
    elif _action.startswith('get_text'):
      '''
      can't execute, will wait
      '''
      self.action_type = 'get_text'
      assert len(self.argv) == 1
    elif _action.startswith('get_attributes'):
      '''
      can't execute, will wait
      '''
      self.action_type = 'get_attributes'
      assert len(self.argv) == 1
    elif _action.startswith('back'):
      '''
      specially handle
      '''
      self.action_type = 'back'
      assert len(self.argv) == 0
    else:
      raise ValueError(f'Unknown action type: {action}')

  @staticmethod
  def _extract_arguments(sentence):
    # This regex will match arguments, including those within quotes
    pattern = re.compile(r"\w+\((.*)\)")
    match = pattern.search(sentence)
    if match:
      args_str = match.group(1)
      args = []
      current_arg = []
      in_quotes = False
      escape_char = False

      for char in args_str:
        if char == "'" and not escape_char:
          in_quotes = not in_quotes
          current_arg.append(char)
        elif char == "\\" and not escape_char:
          escape_char = True
          current_arg.append(char)
        elif char == "," and not in_quotes:
          args.append(''.join(current_arg).strip())
          current_arg = []
        else:
          current_arg.append(char)
          escape_char = False

      if current_arg:
        args.append(''.join(current_arg).strip())

      return args

    return []


class ApiEle():

  def __init__(self, screen_name: str, raw: dict):
    self.id = raw.get('id', 0)
    self.element: str = raw['element']
    self.element_type: str = raw['element_type']
    self.description: str = raw['description']
    self.effect: str = raw.get('effect', None)

    self.screen_name = screen_name
    self.raw_name = raw['api_name']
    self.api_name = screen_name + '__' + self.raw_name
    self.state_tag: str = raw['state_tag']
    self.xpath: str = raw.get('xpath', None) # todo:: maybe not exist, log this
    self.dependency: list[list[str]] = raw.get('paths', [])
    self.dependency_action: list[list[DependentAction]] = []

    for paths in self.dependency:
      _path_actions = []
      for action in paths:
        _path_actions.append(DependentAction(action))
      
      self.dependency_action.append(_path_actions)
  
  def __dict__(self):
    return {
        'id': self.id,
        'element_type': self.element_type,
        'api_name': self.raw_name,
        'element': self.element,
        'description': self.description,
        'effect': self.effect,
        'state_tag': self.state_tag,
        'xpath': self.xpath,
        'paths': [action.raw_action for action in self.dependency_action]
    }


class ApiDoc():

  def __init__(self, doc_path: str):
    self.doc_path = doc_path
    self.doc: dict[str, dict[str, ApiEle]] = {} # screen_name -> api_name -> ApiEle
    self.api_xpath: dict[str, str] = {}
    self.elements: list[ApiEle] = []
    self.skeleton_str2screen_name: dict[str, str] = {}
    self.screen_name2skeleton: dict[str, HTMLSkeleton] = {}

    self.is_updated = False
    
    self.main_screen: str = None
    self._load_api_doc()

  def _load_api_doc(self):
    raw_api_doc = json.load(open(self.doc_path, 'r'))
    len_screen = len(raw_api_doc)

    for k, v in raw_api_doc.items():
      if not self.main_screen:
        self.main_screen = k # first screen is the main screen

      self.screen_name2skeleton[k] = HTMLSkeleton(v['skeleton'])
      self.skeleton_str2screen_name[v['skeleton']] = k
      _elements = {}
      for k_ele, v_ele in v['elements'].items():
        ele = ApiEle(k, v_ele)
        api_name = k + '__' + k_ele
        _elements[api_name] = ele
        self.elements.append(ele)
        self.api_xpath[api_name] = ele.xpath
      self.doc[k] = _elements

    # ! screen and skeleton should be unique (but it's not)
    # assert len(self.skeleton_str2screen_name) == len_screen

  def get_api_xpath(self):
    return self.api_xpath
  
  def get_api_by_name(self, name: str):
    if not name:
      return None
    _screen_name, _api_name = name.split('__')[0], name
    return self.doc[_screen_name].get(_api_name, None)

  def get_dependency(self, api_name: str):
    api = self.get_api_by_name(api_name)
    
    if not api:
      return None, None
    
    return api.paths, api.dependency_action 
  
  def get_xpath_by_name(self, api_name: str, current_skeleton: HTMLSkeleton | str):
    screen_name = api_name.split('__')[0]
    screen = self.doc.get(screen_name, None)
    if not screen:
      screen_name = self.get_screen_name_by_skeleton(current_skeleton)
      if not screen_name:
        return None
      screen = self.doc[screen_name]

    api = screen.get(api_name, None)
    if not api:
      return None
    return api.xpath

  def get_screen_name_by_skeleton(self, skeleton: HTMLSkeleton | str):
    skeleton_str = skeleton if isinstance(skeleton, str) else skeleton.str
    screen_name = self.skeleton_str2screen_name.get(skeleton_str, None)
    if not screen_name:
      count = 3 # todo::
      for _screen_name, screen_skeleton in self.screen_name2skeleton.items():
        common = screen_skeleton.extract_common_skeleton(skeleton)
        _count = common.count()
        if _count > count:
          count = _count
          screen_name = _screen_name
    
    # count is 0, screen_name is None
    return screen_name
  
  def check_api_name_in_current_screen(self, api_name: str, current_skeleton: HTMLSkeleton):
    _screen_name = api_name.split('__')[0]
    _skeleton = self.screen_name2skeleton.get(_screen_name, None)
    if not _skeleton:
      # it should exist, what should be returned? # todo
      # raise ValueError(f'Unknown screen name: {_screen_name}')
      return False
    
    if _skeleton == current_skeleton:
      return True
    
    current_screen_name = self.get_screen_name_by_skeleton(current_skeleton)
    return _screen_name == current_screen_name

  def get_valid_element_list(self, screen_name: str, element_tree: agent_utils.ElementTree):
    elements = self.doc.get(screen_name, None)
    valid_elements: list[ApiEle] = []
    if not elements:
      return valid_elements
    
    for ele in elements.values():
      try:
        target = element_tree.get_ele_by_xpath(ele.xpath)
        if target:
          valid_elements.append(ele)
      except:
        print(ele.xpath)
        raise Exception('internal error: Not Get Current Element, and Retry')
    
    return valid_elements
  
  @staticmethod
  def _get_element_description(ele_list: list[ApiEle], is_show_xpath=False):
    elements_desc = ''
    for ele in ele_list:
      description = ele.description
      elements_desc += f"\n\nelement: {ele.api_name} \n\tDescription: {description} \n\tType: {ele.element_type}"
      if ele.effect:
        elements_desc += f"\n\tEffect: {ele.effect}"
      if is_show_xpath and ele.xpath:
        elements_desc += f"\n\tXPath: {ele.xpath}"
    
    return elements_desc
  
  def get_all_element_desc(self, is_show_xpath=False):
    return self._get_element_description(self.elements, is_show_xpath)
  
  def get_current_element_desc(self, env: interface.AsyncEnv, is_show_xpath=False):
    state = env.get_state(True)
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    current_screen_name = self.get_screen_name_by_skeleton(element_tree.skeleton)
    if not current_screen_name:
      current_screen_name = self.main_screen
    
    # valid_elements
    valid_element_list = self.get_valid_element_list(current_screen_name, element_tree)
    
    return self._get_element_description(valid_element_list, is_show_xpath)
  
  def save(self):
    if self.is_updated:
      doc_data = {}
      for screen_name in self.doc:
        doc_data[screen_name] = {
            'skeleton': self.screen_name2skeleton[screen_name].str,
            'elements': {k: v.__dict__ for k, v in self.doc[screen_name].items()}
        }
      old_doc = json.load(open(self.doc_path, 'r'))
      # bak
      timestamp = datetime.datetime.now().strftime('%m%d%H%M')
      doc_path_bak = self.doc_path.replace('.json', f'_{timestamp}.json')
      json.dump(old_doc, open(doc_path_bak, 'w'), indent=2)
      
      json.dump(doc_data, open(self.doc_path, 'w'), indent=2)