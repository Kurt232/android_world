import os
import json
import re

from android_world.agents.agent_utils import HTMLSkeleton


class DependentAction():

  def __init__(self, action: str):
    action = action.strip()
    self.raw_action: str = action
    self.screen_name: str = None
    self.api_name: str = None
    self.action_type: str = None
    self.argv: list[str] = None
    self.text: str = None

    # screen_name
    m = re.search(r'(\w+)__', action)
    assert m is not None
    self.screen_name = m.group(1)
    action = action[:m.start()] + action[m.end():]

    # argv
    self.argv = self._extract_arguments(action)
    if len(self.argv) > 0:
      self.api_name = self.argv[0]

    # action_type
    if action.startswith('tap'):
      self.action_type = 'tap'
      assert len(self.argv) == 1
    elif action.startswith('long_tap'):
      self.action_type = 'long_tap'
      assert len(self.argv) == 1
    elif action.startswith('set_text'):
      self.action_type = 'set_text'
      assert len(self.argv) == 2
      self.text = self.argv[1].strip("\'\"")
    elif action.startswith('scroll'):
      self.action_type = 'scroll'
      assert len(self.argv) == 2
      direction = self.argv[1].strip("\'\"").lower()
      assert direction in ['up', 'down', 'lift', 'right']  # todo:: left, right
      self.action_type = 'scroll' + ' ' + direction
    elif action.startswith('get_text'):
      self.action_type = 'get_text'
      assert len(self.argv) == 1
    elif action.startswith('get_attributes'):
      self.action_type = 'get_attributes'
      assert len(self.argv) == 1
    elif action.startswith('back'):
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

  def __init__(self, raw: dict):
    self.element: str = raw['element']
    self.element_type: str = raw['element_type']
    self.description: str = raw['description']
    self.effect: str = raw.get('effect', None)

    self.full_api_name = raw['api_name']
    
    tmp_name = raw['api_name'].split('__')
    assert len(tmp_name) == 2
    self.scree_name: str = tmp_name[0]
    self.api_name: str = tmp_name[1]

    self.state_tag: str = raw['state_tag']
    self.xpath: str = raw['xpath']
    self.dependency: list[list[str]] = raw['paths']
    self.dependency_action: list[list[DependentAction]] = []

    for paths in self.dependency:
      _path_action = []
      for action in paths:
        _path_action.append(DependentAction(action))


class ApiDoc():

  def __init__(self, app_name: str, api_doc_dir: str = "tmp/docs"):
    self.api_doc_path = os.path.join(api_doc_dir, app_name + '.json')
    self.doc: dict[str, dict[str, ApiEle]] = {}
    self.api_xpath: dict[str, str] = {}
    self.skeleton_str2screen_name: dict[str, str] = {}
    self.screen_name2skeleton: dict[str, HTMLSkeleton] = {}

    self.main_screen: str = None
    self.load_api_doc()

  def load_api_doc(self):
    raw_api_doc = json.load(open(self.api_doc_path, 'r'))
    len_screen = len(raw_api_doc)

    for k, v in raw_api_doc.items():
      if not self.main_screen:
        self.main_screen = k

      self.screen_name2skeleton[k] = HTMLSkeleton(v['skeleton'])
      self.skeleton_str2screen_name[v['skeleton']] = k
      _elements = {}
      for k_ele, v_ele in v['elements'].items():
        ele = ApiEle(v_ele)
        _elements[k_ele] = ele
        if ele.xpath: # existing null xpath
          self.api_xpath[k + '__' + k_ele] = ele.xpath
      self.doc[k] = _elements

    # ! screen and skeleton should be unique (but it's not)
    # assert len(self.skeleton_str2screen_name) == len_screen

  def get_api_xpath(self):
    return self.api_xpath

  def get_dependency(self, skeleton: HTMLSkeleton, api_name: str):
    count = -1
    _screen_name = None
    for screen_name, screen_skeleton in self.screen_name2skeleton.items():
      common = screen_skeleton.extract_common_skeleton(skeleton)
      _count = common.count()
      if _count > count:
        count = _count
        _screen_name = screen_name

    if not _screen_name:
      _screen_name = self.main_screen

    api = self.doc[_screen_name][api_name]
    return api.dependency, api.dependency_action 
  
  def get_xpath_by_name(self, screen_name: str, api_name: str):
    screen = self.doc.get(screen_name, None)
    if not screen:
      return None
    api = screen.get(api_name, None)
    if not api:
      return None
    return api.xpath
