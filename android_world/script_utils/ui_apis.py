import json
import os
import re
import pdb
import yaml
import inspect
import time

from android_world.agents.agent_utils import ElementTree, EleAttr
from android_world.agents import agent_utils
from android_world.agents import infer
from android_world.env import interface
from android_world.env import json_action

from android_world.script_utils import tools
from android_world.script_utils.api_doc import ApiDoc

# Constants
MAX_SCROLL_NUM = 4

api_names = [
    'long_tap', 'tap', 'set_text', 'scroll', 'get_text', 'get_attributes',
    'back', 'get_ui_tree', 'check_ele_exist'
]

ACTION_COUNT = 0
MAX_ACTION_COUNT = 100


def set_action_count(count):
  global ACTION_COUNT
  ACTION_COUNT = count


def check_aciton_count():
  global ACTION_COUNT
  if ACTION_COUNT >= MAX_ACTION_COUNT:
    raise Exception(
        f'Action count exceeds the maximum limit: {MAX_ACTION_COUNT}. The script may be stuck in an infinite loop. Please check the script.'
    )
  ACTION_COUNT += 1


def sanitize_name(name):
  # To make it a valid python variable, replace all non-word characters with '_', and replace the first digit with '_'
  return re.sub(r'\W|^(?=\d)', '_', name)


def regenerate_script(script, verifier_instant_name, android_env_name,
                      save_path_name, api_xpaths_instant_name):
  '''
    find element_lists and instantiate them, remove '$' from element_selectors, add instant_name prefix to all apis
    '''
  pattern = re.compile(r'^.*?\$([\w%]+).*?(\[\d+\]|\.match\([^)]+\)).*$',
                       re.MULTILINE)
  script_lines = script.split('\n')
  modified_lines = [
      f'def autodroidv2_task_solution_code({verifier_instant_name}, {android_env_name}, {save_path_name}, {api_xpaths_instant_name}):'
  ]  # def a function because of the necessity of inspecting the script
  all_appeared_api_names = []
  line_mappings = {
  }  # key: compiled script line number, value: original script line number
  compiled_line_num = 1  # the first line is the function definition line autodroidv2_task_solution_code()
  for original_line_num, line in enumerate(script_lines):
    match = pattern.match(line)
    if match:
      # for matching, indexing operation statements.
      element_name = match.group(1)
      sanitized_element_name = sanitize_name(element_name)
      beginning_tabs = tools.get_leading_tabs(line)
      instantiate_statement = f'{beginning_tabs}{sanitized_element_name} = ElementList(\'{element_name}\', None, {android_env_name}, {save_path_name}, {api_xpaths_instant_name}, {verifier_instant_name})'
      modified_lines.append(f'\t{instantiate_statement}')
      line_mappings[compiled_line_num] = original_line_num
      compiled_line_num += 1

      line = line.replace(f'${element_name}', sanitized_element_name)
    else:
      # for tapping, set_text, etc. statements
      api_name_pattern = r'\$([\w%]+)'  # also match apis with %, for example, font_size_150%
      matches = re.findall(api_name_pattern, line)
      if matches:
        for api_name in matches:
          sanitized_api_name = sanitize_name(api_name)
          if sanitized_api_name not in all_appeared_api_names:
            all_appeared_api_names.append(api_name)
            beginning_tabs = tools.get_leading_tabs(line)
            instantiate_statement = f'{beginning_tabs}{sanitized_api_name} = ElementList(\'{api_name}\', None, {android_env_name}, {save_path_name},{api_xpaths_instant_name}, {verifier_instant_name})'
            modified_lines.append(f'\t{instantiate_statement}')
            line_mappings[compiled_line_num] = original_line_num
            compiled_line_num += 1

          line = line.replace(f'${api_name}', sanitized_api_name)

    modified_lines.append(f'\t{line}')
    line_mappings[compiled_line_num] = original_line_num
    compiled_line_num += 1

  modified_lines.append(
      f'autodroidv2_task_solution_code({verifier_instant_name}, {android_env_name}, {save_path_name}, {api_xpaths_instant_name})'
  )
  script = '\n'.join(modified_lines)

  for api_name in api_names:
    script = script.replace(f'{api_name}(',
                            f'{verifier_instant_name}.{api_name}(')
  script = script.replace(f'long_{verifier_instant_name}.tap(', 'long_tap(')
  return script, line_mappings


def _save2yaml(file_name,
               state_prompt,
               idx,
               inputs=None,
               action_type='touch',
               state_str=None,
               structure_str=None,
               tag=None,
               width=None,
               height=None,
               raw_prompt=None,
               raw_answer=None,
               currently_executing_code=None):
  if not os.path.exists(file_name):
    tmp_data = {'step_num': 0, 'records': []}
    with open(file_name, 'w', encoding='utf-8') as f:
      yaml.dump(tmp_data, f)

  with open(file_name, 'r', encoding='utf-8') as f:
    old_yaml_data = yaml.safe_load(f)
  new_records = old_yaml_data['records']
  new_records.append({
      'State': state_prompt,
      'Choice': idx,
      'Action': action_type,
      'Input': inputs,
      'state_str': state_str,
      'structure_str': structure_str,
      'tag': tag,
      'width': width,
      'height': height,
      'raw_prompt': raw_prompt,
      'raw_answer': raw_answer,
      'currently_executing_code': currently_executing_code
  })
  data = {
      'step_num': len(list(old_yaml_data['records'])),
      'records': new_records
  }
  t1 = time.time()
  with open(file_name, 'w', encoding='utf-8') as f:
    yaml.dump(data, f)
  print(f'save to yaml time: {time.time() - t1}')


# todo
# def save_current_ui_to_log(env: interface.AsyncEnv,
#                            save_path: str,
#                            api_name,
#                            currently_executing_code=None):
#   log_path = os.path.join(save_path,
#                           f'log_{input_policy.task_id}.yaml')
#   state = env.get_state()
#   element_tree = agent_utils.forest_to_element_tree(state.forest)
#   state_desc = element_tree.str

#   if os.path.exists(log_path):
#     output_log = tools.load_yaml_file(log_path)
#     if len(output_log['records']) == 0:
#       return
#     last_state_str = output_log['records'][-1]['state_str']

#     state_str = agent_utils.get_state_str(state.forest)
#     if state_str != last_state_str:

#       output_log['records'].append({
#           'Action': None,
#           'Choice': 'crashed',
#           'Input': None,
#           'State': state_desc,
#           'tag': state.tag,
#           'width': current_state.width,
#           'height': current_state.height,
#           'raw_prompt': None,
#           'raw_answer': None,
#           'currently_executing_code': currently_executing_code
#       })
#       tools.dump_yaml_file(log_path, output_log)

#   else:
#     output_log = {
#         'step_num':
#             0,
#         'records': [{
#             'Action': None,
#             'Choice': 'crashed',
#             'Input': None,
#             'State': state_desc,
#             'state_str': current_state.state_str,
#             'structure_str': current_state.structure_str,
#             'tag': current_state.tag,
#             'width': current_state.width,
#             'height': current_state.height,
#             'raw_prompt': None,
#             'raw_answer': None,
#             'currently_executing_code': currently_executing_code
#         }]
#     }
#     tools.dump_yaml_file(log_path, output_log)

# In the script, except for the common python control flow (for, if-else, function def/calls, etc.), you can use the following APIs:
# - tap(<element_selector>): tap on the element. Almost all elements can be taped. If an element's attribute checked=false or selected=false, tapping it can make it checked or selected, vice versa.
# - set_text(<element_selector>, <text>): set the text of the element to <text>. Only editable text fields can be set text.
# - get_text(<element_selector>): return the text of the element as a string.
# - get_attributes(<element_selector>): return the attributes of the element as a dict, dict keys include "selected", "checked", "scrollable", dict values are boolean. eg. get_attributes($files[3])["selected"].
# - back(): close the current window

# The <element_selector> primitive is used to select an element, possible ways of selection include:
# - $<element id>, eg. $settings_button
# - $<element_list>[<idx>]: the idx-th in the element list. eg. $my_items[1]

# The <element_list> primitive is used to select a list of elements, possible ways of selection include:
# - <element_selector>: the items in the list element identified by <element_selector>. eg. $my_items
# - <element_list>.match(<text or attribute dict>): the elements in the element list that match the given text or attribute dict. eg. $my_items.match("key words") or $my_items.match({"selected": true})
# You can use len(<element_list>) to get the total number of items in an element list.

# class Element:
#     def __init__(self, api_name=None, xpath=None) -> None:
#         self.api_name = api_name
#         self.xpath = xpath

#     def get_ele_api_name(self):
#         return self.api_name

#     def get_ele_xpath(self):
#         return self.xpath


class ElementList:

  def __init__(self, api_name, api_xpath, env: interface.AsyncEnv,
               save_path: str, api_xpaths, verifier) -> None:
    # all element_lists can be uniquely identified by their api_xpath. If one api_name is provided, we can retrieve its xpath from api_xpaths. If api_name is not provided, such as a dynamic element at runtime, then its xpath must be provided.
    self.env = env
    self.save_path = save_path

    self.api_name = api_name
    self.api_xpaths = api_xpaths
    if self.api_name:
      self.check_api_name(api_name)
    if not api_xpath:
      self.element_list_xpath = self.api_xpaths[api_name]
    else:
      self.element_list_xpath = api_xpath
    self.verifier = verifier
    self.index = 0

  def _save_getting_info_action(self, action_type, current_code_line,
                                lineno_in_original_script, original_code_line):
    # yaml_path = os.path.join(self.save_path,
    #                          f'log_{self.input_policy.task_id}.yaml')# todo
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    state_desc = element_tree.str
    # _save2yaml(yaml_path,
    #            state_desc,
    #            idx=None,
    #            inputs=None,
    #            action_type=action_type,
    #            state_str=state.state_str,
    #            structure_str=state.structure_str,
    #            tag=state.tag,
    #            width=state.width,
    #            height=state.height,
    #            raw_prompt=None,
    #            raw_answer=None,
    #            currently_executing_code={
    #                'current_code': current_code_line,
    #                'original_lineno': lineno_in_original_script,
    #                'original_code': original_code_line
    #            })

  def check_api_name(self, api_name):
    if api_name not in self.api_xpaths.keys():
      # find the first line with the api_name in the original script (combined with the preparation, this is to stay the same with tap, set_text, etc.)
      code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
      # lines = original_script.split('\n')
      line_with_api_name = None
      for line_num, line in enumerate(code_lines):
        if api_name in line:
          line_with_api_name = line.strip()
          lineno_in_original_script = tools.load_json_file(
              'tmp/line_mappings.json')[str(line_num)]
          original_code_line = tools.load_txt_file(
              'tmp/combined_code.txt').split('\n')[lineno_in_original_script]
          break
      currently_executing_code = {
          'current_code': line_with_api_name,
          'original_lineno': lineno_in_original_script,
          'original_code': original_code_line
      }

      # save_current_ui_to_log(self.input_policy,
      #                        api_name,
      #                        currently_executing_code=currently_executing_code)
      raise Exception(
          f'Error: Element {api_name} does not exist in the app! Please use the real element name! '
      )

  def convert_ele_attr_to_elementlist(self, ele_attr):
    ele_xpath = f"//{ele_attr.type_}[@id='{ele_attr.id}']"
    elementlist = ElementList(api_name=None,
                              api_xpath=ele_xpath,
                              input_policy=self.input_policy,
                              api_xpaths=self.api_xpaths,
                              verifier=self.verifier)
    return ele_xpath, elementlist

  def navigate_to_api_name(self, api_name, caller_type, statement):
    # if the api_name is provided, then the element_list is selected from the api document, then we should check its dependency
    if api_name:
      target_ele, element_tree = self.verifier.navigate_and_get_target_element(
          api_name, caller_type, statement)
      if not target_ele:
        raise Exception(f'Element {api_name} not found! ')

  def __getitem__(self, selector):
    global ACTION_COUNT

    # get the currently executing code
    code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"getting the {selector} item at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file('tmp/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file('tmp/combined_code.txt').split(
        '\n')[lineno_in_original_script]

    self.navigate_to_api_name(self.api_name,
                              caller_type='index',
                              statement={
                                  'current_code': current_code_line,
                                  'original_lineno': lineno_in_original_script,
                                  'original_code': original_code_line
                              })
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    target_ele_group = element_tree.get_ele_by_xpath(self.element_list_xpath)

    # Default to integer index if not a custom selector
    if isinstance(selector, int):
      ele_attr = element_tree.get_children_by_idx(target_ele_group, selector)
      matched_xpath, matched_ele = self.convert_ele_attr_to_elementlist(
          ele_attr)
      # self._save_getting_ele_info_action_to_yaml('index', f'{self.api_name}[{selector}]', matched_xpath)
      return matched_ele
    # # Handle slice objects
    # elif isinstance(selector, slice):
    #     return self.data[selector.start:selector.stop:selector.step]
    check_aciton_count()
    raise ValueError("Invalid selector")

  def __iter__(self):
    '''
        in order to support iteration, we need to return an iterator object from __iter__() method.
        '''
    return self

  def __next__(self):
    '''
        return the next element in the current element's children to support iteration.
        '''
    global ACTION_COUNT
    # get the currently executing code
    code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file('tmp/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file('tmp/combined_code.txt').split(
        '\n')[lineno_in_original_script]
    self._save_getting_info_action('index', current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)

    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    target_ele_group = element_tree.get_ele_by_xpath(self.element_list_xpath)

    if not target_ele_group:
      self.navigate_to_api_name(
          self.api_name,
          caller_type='next',
          statement={
              'current_code': current_code_line,
              'original_lineno': lineno_in_original_script,
              'original_code': original_code_line
          })
      state = self.env.get_state()
      element_tree = agent_utils.forest_to_element_tree(state.forest)
      target_ele_group = element_tree.get_ele_by_xpath(self.element_list_xpath)

    ele_list_children = element_tree.get_children_by_ele(target_ele_group)
    if not ele_list_children:
      raise StopIteration
    # ACTION_COUNT += 1
    check_aciton_count()
    if self.index < len(ele_list_children):
      ele_attr = ele_list_children[self.index]
      matched_xpath, matched_ele = self.convert_ele_attr_to_elementlist(
          ele_attr)
      self.index += 1
      return matched_ele
    else:
      self.index = 0
      raise StopIteration

  def match(self, match_data):
    global ACTION_COUNT

    # get the currently executing code
    code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"match: {match_data} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file('tmp/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file('tmp/combined_code.txt').split(
        '\n')[lineno_in_original_script]

    self._save_getting_info_action('match', current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)

    self.navigate_to_api_name(self.api_name,
                              caller_type='match',
                              statement={
                                  'current_code': current_code_line,
                                  'original_lineno': lineno_in_original_script,
                                  'original_code': original_code_line
                              })
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    target_ele = element_tree.get_ele_by_xpath(self.element_list_xpath)
    ele_list_children = element_tree.get_children_by_ele(target_ele)

    matched_elements, matched_xpaths = [], []
    for ele in ele_list_children:
      # ele_dict = ele.dict()
      if isinstance(match_data, str):
        if ele.is_match(match_data):
          matched_xpath, matched_ele = self.convert_ele_attr_to_elementlist(ele)
          matched_elements.append(matched_ele)
          matched_xpaths.append(matched_xpath)
      elif isinstance(match_data, dict):
        ele_dict = ele.dict()
        if all(ele_dict[key] == value for key, value in match_data.items()):
          matched_xpath, matched_ele = self.convert_ele_attr_to_elementlist(ele)
          matched_elements.append(matched_ele)
          matched_xpaths.append(matched_xpath)

    # ACTION_COUNT += 1
    check_aciton_count()
    return matched_elements

  def __len__(self):
    global ACTION_COUNT

    # get the currently executing code
    code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(f"getting length at line {lineno}, code is:{code_lines[lineno - 1]}")
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file('tmp/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file('tmp/combined_code.txt').split(
        '\n')[lineno_in_original_script]
    self._save_getting_info_action('len', current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)

    self.navigate_to_api_name(self.api_name,
                              caller_type='len',
                              statement={
                                  'current_code': current_code_line,
                                  'original_lineno': lineno_in_original_script,
                                  'original_code': original_code_line
                              })
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    target_ele = element_tree.get_ele_by_xpath(self.element_list_xpath)
    # ele_list_children = element_tree.get_children_by_ele(target_ele)
    ele_list_children = target_ele.children
    # ACTION_COUNT += 1
    check_aciton_count()
    return len(ele_list_children)

  # def _save_getting_ele_info_action_to_yaml(self, action_type, action_statement, matched_xpath):
  #     '''
  #     @action_type: match/index/len
  #     @action_statement: the statement of the action, such as "open_note_title_list[0]"
  #     @matched_xpath: the xpath of the matched element
  #     '''
  #     old_state = self.input_policy.device.get_current_state()
  #     element_tree = self.input_policy.memory._memorize_state(old_state)['element_tree']
  #     state_desc = element_tree.get_str(is_color=False)

  #     statement = f'{action_statement} -> {matched_xpath}'

  #     yaml_path = os.path.join(self.input_policy.device.output_dir, f'log_{self.input_policy.task_id}.yaml')
  #     _save2yaml(yaml_path, state_desc, idx=None, inputs=None, action_type=action_type, state_str=old_state.state_str, structure_str=old_state.structure_str, tag=old_state.tag, width=old_state.width, height=old_state.height, raw_prompt=None, raw_answer=None, currently_executing_code=statement)


class Verifier:

  # Wait a few seconds for the screen to stabilize after executing an action.
  WAIT_AFTER_ACTION_SECONDS = 2.0

  def __init__(self, env: interface.AsyncEnv,
               save_path: str, app_name: str, api_xpaths, doc: ApiDoc) -> None:
    # android world
    self.env = env
    self.save_path = save_path
    self.app_name = app_name
    self.api_xpaths = api_xpaths
    self.doc = doc
    # autodroid

  def get_action_from_xpath(self, element_tree: ElementTree, xpath: str,
                            action_type: str, input_text: str):

    def get_needed_ele_property_from_action_type(action_type):
      if action_type == 'touch':
        return 'clickable'
      if action_type == 'long_touch':
        return 'long_clickable'
      if action_type == 'scroll up' or action_type == 'scroll down':
        return 'scrollable'
      if action_type == 'set_text':
        return 'editable'
      if 'select' in action_type:
        return 'checkable'
      return None

    ele = element_tree.get_ele_by_xpath(xpath)
    if not ele:
      return {"action_type": "status", "goal_status": "infeasible"}

    # the action is supposed to be performed, so now we should find an executable element in the current UI element's children
    if action_type in [
        'touch', 'long_touch', 'select', 'unselect', 'scroll up', 'scroll down',
        'scroll', 'set_text'
    ]:
      needed_property = get_needed_ele_property_from_action_type(action_type)
      if needed_property and not ele.get_attributes().get(
          needed_property, False):
        all_children = element_tree.get_all_children_by_ele(ele)
        for child in all_children:
          if child.get_attributes().get(needed_property, False):
            ele = child
            break
    # todo:: can we need to check whether the ele existing after property checking
    # file_path = os.path.join(self.device.output_dir, f'log_{self.task_id}.yaml')
    # _save2yaml(file_path,
    #            ui_tree_str,
    #            ele.id,
    #            input_text,
    #            action_type,
    #            state.state_str,
    #            state.structure_str,
    #            state.tag,
    #            state.width,
    #            state.height,
    #            currently_executing_code=self.code_to_be_executed['statement'])

    return agent_utils.convert_action(action_type, ele, input_text)

  def scroll_and_find_target_ele(self,
                                 element_tree: ElementTree,
                                 xpath,
                                 action_type,
                                 text,
                                 direction='DOWN'):
    all_ele_descs_during_scrolling = []

    for ele_id in element_tree.scrollable_ele_ids:
      origin_ele = element_tree.ele_map[ele_id]
      ele_properties_without_idx = {
          'resource_id': origin_ele.resource_id,
          'class_name': origin_ele.class_name,
          'content_description': origin_ele.content_description,
          'bound_box': origin_ele.bound_box,
      }

      for _ in range(MAX_SCROLL_NUM):

        state = self.env.get_state()
        element_tree = agent_utils.forest_to_element_tree(state.forest)

        target_action = self.get_action_from_xpath(element_tree, xpath,
                                                   action_type, text)
        if target_action.get('goal_status', None) != 'infeasible':
          return target_action
        ele_descs = element_tree.get_ele_descs_without_text()
        # judge whether there is a new view after scrolling, if no new element found, return
        scrolled_new_views = []
        for scrolled_view in ele_descs:
          if scrolled_view not in all_ele_descs_during_scrolling:
            scrolled_new_views.append(scrolled_view)
            all_ele_descs_during_scrolling.append(scrolled_view)
        if len(scrolled_new_views) == 0:
          break

        # ui_tree_str = element_tree.str
        # file_path = os.path.join(self.device.output_dir,
        #                          f'log_{self.task_id}.yaml')

        # _save2yaml(
        #     file_path,
        #     ui_tree_str,
        #     scroller_id,
        #     None,
        #     f'scroll {direction}',
        #     scrolled_state.state_str,
        #     scrolled_state.structure_str,
        #     scrolled_state.tag,
        #     scrolled_state.width,
        #     scrolled_state.height,
        #     currently_executing_code=self.code_to_be_executed['statement'])
        target_ele = element_tree.get_ele_by_properties(
            ele_properties_without_idx)
        if target_ele:
          self.env.execute_action(
              json_action.JSONAction(
                  **{
                      "action_type": "scroll",
                      "index": target_ele.local_id,
                      "direction": direction
                  }))
          time.sleep(self.WAIT_AFTER_ACTION_SECONDS)
    return {"action_type": "status", "goal_status": "infeasible"}

  def execute_action(self, ele_data: dict):
    global ACTION_COUNT
    
    api_name = ele_data['api_name']
    if not api_name:
      return
    
    if ACTION_COUNT == 0:
      self.env.execute_action(
          json_action.JSONAction(**{
              "action_type": "open_app",
              "app_name": self.app_name
          }))
      time.sleep(self.WAIT_AFTER_ACTION_SECONDS)

    code_to_be_executed = ele_data

    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    # first execute the code
    xpath = code_to_be_executed['xpath']
    action_type = code_to_be_executed['action_type']
    text = code_to_be_executed['text']

    if action_type == None:
      return

    executable_action = self.get_action_from_xpath(element_tree, xpath,
                                                   action_type, text)

    if executable_action.get('goal_status', None) != 'infeasible':
      self.env.execute_action(json_action.JSONAction(**executable_action))
      time.sleep(self.WAIT_AFTER_ACTION_SECONDS)
      return

    # could not find a target element in the current UI, find in the dependencies
    executable_action = self.scroll_and_find_target_ele(element_tree, xpath,
                                                        action_type, text)

    # could not find a target element in the current UI, find in the dependencies
    if executable_action.get('goal_status', None) != 'infeasible':
      self.env.execute_action(json_action.JSONAction(**executable_action))
      time.sleep(self.WAIT_AFTER_ACTION_SECONDS)
      return

    ## dependency
    # we have executed all the dependencies, but still not found the target element
    done = False
    while not done: # todo:: limit the max number of retry
      state = self.env.get_state()
      element_tree = agent_utils.forest_to_element_tree(state.forest)
      current_skeleton = element_tree.skeleton
      _, dependency_action = self.doc.get_dependency(current_skeleton, api_name)
      
      count = 0
      for action_list in dependency_action:
        count += 1
        
        is_match = False
        dep_id = -1
        for idx, action in enumerate(reversed(action_list)):
          _screen_name = action.screen_name
          target_skeleton = self.doc.screen_name2skeleton[_screen_name]
          
          # use `is` to judge whether the two skeletons are the same one
          # use `==` to judge whether the two skeletons are the same skeleton
          if current_skeleton != current_skeleton.extract_common_skeleton(target_skeleton):
            if is_match:
              break
            else:
              continue
          
          action_type = action.action_type
          text = action.text
          xpath = self.doc.get_xpath_by_name(_screen_name, action.api_name)
          executable_action = self.get_action_from_xpath(
              element_tree, xpath, action_type, text)
          
          if executable_action.get('goal_status', None) == 'infeasible':
            if is_match:
              break
            else:
              continue
          
          # execute the action
          is_match = True
          dep_id = idx
          self.env.execute_action(json_action.JSONAction(**executable_action))
          time.sleep(self.WAIT_AFTER_ACTION_SECONDS)
        
        if dep_id == len(action_list) - 1:
          done = True
        
        # executed action and changed the screen, we need to find new dependency
        if is_match:
          break
        
      if count == len(dependency_action) and not done:
        # fail to solve the dependency
        break
    
    if not done:
      raise Exception(f'Action not found when executing tap {api_name}')
    return

  def check_output_crash(self, api_name):
    output_log = tools.load_yaml_file(
        os.path.join(self.save_path, f'log.yaml')
    )  # todo:: what's the task_id
    # if output_log['records'][-1]['Choice'] == 'crashed':
    #   raise Exception(f'Action not found when executing tap {api_name}')

  def navigate_and_get_target_element(self, element_selector, caller_type,
                                      statement):
    # t1 = time.time()
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    # print(f'get current state time: {time.time() - t1}')
    # t2 = time.time()
    # for actions like getting length, indexing, or matching, the element_selector is a string
    if isinstance(element_selector, str):
      element_selector = element_selector.split('$')[-1]

      element_selector_xpath = self.api_xpaths[element_selector]
      element_selector_api_name = element_selector
    else:
      if isinstance(element_selector, list):
        element_selector = element_selector[0]
      element_selector_xpath = element_selector.element_list_xpath
      element_selector_api_name = element_selector.api_name if element_selector.api_name else element_selector.element_list_xpath

    target_ele = element_tree.get_ele_by_xpath(element_selector_xpath)
    # print(f'get target element time: {time.time() - t2}')
    if not target_ele:
      ele_data = {
          'xpath': element_selector_xpath,
          'api_name': None,
          'text': None,
          'action_type': None,
          'statement': statement
      }

      self.execute_action(ele_data)
      self.check_output_crash(element_selector_xpath)
      state = self.env.get_state()
      element_tree = agent_utils.forest_to_element_tree(state.forest)
      target_ele = element_tree.get_ele_by_xpath(element_selector_xpath)

    return target_ele, element_tree

  def _save_getting_info_action(self, action_type, current_code_line,
                                lineno_in_original_script, original_code_line):
    # yaml_path = os.path.join(self.input_policy.device.output_dir,
    #                          f'log_{self.input_manager.task_id}.yaml')
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    state_desc = element_tree.str
    # _save2yaml(yaml_path,
    #            state_desc,
    #            idx=None,
    #            inputs=None,
    #            action_type=action_type,
    #            state_str=state.state_str,
    #            structure_str=state.structure_str,
    #            tag=state.tag, # todo::
    #            width=state.width,
    #            height=state.height,
    #            raw_prompt=None,
    #            raw_answer=None,
    #            currently_executing_code={
    #                'current_code': current_code_line,
    #                'original_lineno': lineno_in_original_script,
    #                'original_code': original_code_line
    #            })

  def get_ui_tree(self):
    '''
        return the current UI tree as a string.
        '''
    global ACTION_COUNT
    if ACTION_COUNT == 0:
      self.env.execute_action( # maybe it's unnecessary
          json_action.JSONAction(**{
              "action_type": "open_app",
              "app_name": self.app_name
          }))

    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    element_tree_str = element_tree.str
    # ACTION_COUNT += 1  # to ensure the app do not restart after getting the ui tree
    check_aciton_count()
    return element_tree_str

  def check_ele_exist(self, element_selector):
    '''
        check whether the element exists in the current UI
        '''
    global ACTION_COUNT
    if ACTION_COUNT == 0:
      self.env.execute_action(
          json_action.JSONAction(**{
              "action_type": "open_app",
              "app_name": self.app_name
          }))

    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    if isinstance(element_selector, list):
      element_selector = element_selector[0]
    selector_xpath = element_selector.element_list_xpath
    if element_tree.get_ele_by_xpath(selector_xpath):
      return True
    else:
      return False

  def tap(self, button_api):
    global ACTION_COUNT
    # get the currently executing code
    code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"Tap: {button_api} at line {lineno}, code is:{code_lines[lineno - 1]}")
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file('tmp/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file('tmp/combined_code.txt').split(
        '\n')[lineno_in_original_script]

    if isinstance(button_api, str):
      print(f'try to tap: {button_api}, current action account: {ACTION_COUNT}')
      button_api_name = button_api.split('$')[-1]
      ele_data = {
          'xpath': self.api_xpaths[button_api_name],
          'api_name': button_api_name,
          'text': None,
          'action_type': 'touch',
      }

    else:
      # this button is a component from an element list, so it already exists in the UI
      if isinstance(button_api, list):
        button_api = button_api[0]
      button_api_name = button_api.api_name if button_api.api_name else button_api.element_list_xpath

      print(
          f'try to tap: {button_api_name}, current action account: {ACTION_COUNT}'
      )


      ele_data = {
          'xpath': button_api.element_list_xpath,
          'api_name': button_api.api_name,
          'text': None,
          'action_type': 'touch',
          'statement': {
              'current_code': current_code_line,
              'original_lineno': lineno_in_original_script,
              'original_code': original_code_line
          }
      }

    self.execute_action(ele_data)
    self.check_output_crash(button_api_name)
    # ACTION_COUNT += 1
    check_aciton_count()

  def long_tap(self, button_api):
    global ACTION_COUNT
    # get the currently executing code
    code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"long tap: {button_api} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file('tmp/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file('tmp/combined_code.txt').split(
        '\n')[lineno_in_original_script]

    if isinstance(button_api, str):
      print(f'try to tap: {button_api}, current action account: {ACTION_COUNT}')
      button_api_name = button_api.split('$')[-1]
      ele_data = {
          'xpath': self.api_xpaths[button_api_name],
          'api_name': button_api_name,
          'text': None,
          'action_type': 'touch'
      }

    else:
      # this button is a component from an element list, so it already exists in the UI
      if isinstance(button_api, list):
        button_api = button_api[0]
      button_api_name = button_api.api_name if button_api.api_name else button_api.element_list_xpath

      print(
          f'try to tap: {button_api_name}, current action account: {ACTION_COUNT}'
      )


      ele_data = {
          'xpath': button_api.element_list_xpath,
          'api_name': button_api.api_name,
          'text': None,
          'action_type': 'long_touch',
          'statement': {
              'current_code': current_code_line,
              'original_lineno': lineno_in_original_script,
              'original_code': original_code_line
          }
      }

    self.execute_action(ele_data)
    self.check_output_crash(button_api_name)
    # ACTION_COUNT += 1
    check_aciton_count()

  def set_text(self, text_api, text):
    global ACTION_COUNT
    # get the currently executing code
    code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"settext: {text_api} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file('tmp/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file('tmp/combined_code.txt').split(
        '\n')[lineno_in_original_script]

    if isinstance(text_api, str):
      text_api_name = text_api.split('$')[-1]
      ele_data = {
          'xpath': self.api_xpaths[text_api_name],
          'api_name': text_api_name,
          'text': text,
          'action_type': 'set_text'
      }
    else:
      if isinstance(text_api, list):
        text_api = text_api[0]
      text_api_name = text_api.api_name if text_api.api_name else text_api.element_list_xpath

      ele_data = {
          'xpath': text_api.element_list_xpath,
          'api_name': None,
          'text': text,
          'action_type': 'set_text',
          'statement': {
              'current_code': current_code_line,
              'original_lineno': lineno_in_original_script,
              'original_code': original_code_line
          }
      }

    # self.input_policy.action_count = action_count
    # if action_count == 0:
    #     self.input_policy.start(input_manager=self.input_manager, restart_first=True)
    # else:
    #     self.input_policy.start(input_manager=self.input_manager, restart_first=False)
    self.execute_action(ele_data)
    self.check_output_crash(text_api_name)
    # ACTION_COUNT += 1
    check_aciton_count()

  def scroll(self, scroller_api, direction):
    global ACTION_COUNT
    # get the currently executing code
    code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"scroll {direction}: {scroller_api} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file('tmp/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file('tmp/combined_code.txt').split(
        '\n')[lineno_in_original_script]

    if isinstance(scroller_api, str):
      scroller_api_name = scroller_api.split('$')[-1]
      if 'up' in direction.lower():
        direction_str = 'up'
      elif 'down' in direction.lower():
        direction_str = 'down'
      elif 'left' in direction.lower():
        direction_str = 'left'
      elif 'right' in direction.lower():
        direction_str = 'right'
      else:
        direction_str = 'down'
      ele_data = {
          'xpath': self.api_xpaths[scroller_api_name],
          'api_name': scroller_api_name,
          'text': None,
          'action_type': f'scroll {direction_str}'
      }

    else:
      # this button is a component from an element list, so it already exists in the UI
      if isinstance(scroller_api, list):
        scroller_api = scroller_api[0]
      scroller_api_name = scroller_api.api_name if scroller_api.api_name else scroller_api.element_list_xpath
      direction_str = 'up' if 'up' in direction.lower() else 'down'


      ele_data = {
          'xpath': scroller_api.element_list_xpath,
          'api_name': scroller_api_name,
          'text': None,
          'action_type': f'scroll {direction_str}',
          'statement': {
              'current_code': current_code_line,
              'original_lineno': lineno_in_original_script,
              'original_code': original_code_line
          }
      }

    self.execute_action(ele_data)
    self.check_output_crash(scroller_api_name)
    # ACTION_COUNT += 1
    check_aciton_count()

  def get_text(self, element_selector):
    global ACTION_COUNT
    '''
        return the text of the element as a string.
        '''

    # get the currently executing code
    code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"get_text: {element_selector} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file('tmp/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file('tmp/combined_code.txt').split(
        '\n')[lineno_in_original_script]

    target_ele, element_tree = self.navigate_and_get_target_element(
        element_selector,
        caller_type='get_text',
        statement={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        })

    self._save_getting_info_action('get_text', current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)

    check_aciton_count()
    if not target_ele:
      raise Exception(
          f'Element not found when executing get_text {element_selector}')
    else:
      text = element_tree.get_text(target_ele)
      text = text.replace('--', ' ')
      return text

  def get_attributes(self, element_selector):
    global ACTION_COUNT
    '''
    return the attributes of the element as a dict, dict keys include "selected", "checked", "scrollable", dict values are boolean. eg. get_attributes($files[3])["selected"].
    '''

    # get the currently executing code
    code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"get_attributes: {element_selector} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file('tmp/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file('tmp/combined_code.txt').split(
        '\n')[lineno_in_original_script]

    target_ele, _ = self.navigate_and_get_target_element(
        element_selector,
        caller_type='get_attributes',
        statement={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        })

    # yaml_path = os.path.join(self.input_policy.device.output_dir, f'log_{self.input_manager.task_id}.yaml')
    # state = self.input_policy.device.get_current_state()
    # element_tree = self.input_policy.memory._memorize_state(state)['element_tree']
    # state_desc = element_tree.get_str(is_color=False)
    # _save2yaml(yaml_path, state_desc, idx=None, inputs=None, action_type='get_attributes', state_str=state.state_str, structure_str=state.structure_str, tag=state.tag, width=state.width, height=state.height, raw_prompt=None, raw_answer=None, currently_executing_code={'current_code': current_code_line, 'original_lineno': lineno_in_original_script, 'original_code': original_code_line})
    self._save_getting_info_action('get_attributes', current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)

    check_aciton_count()
    if not target_ele:
      raise Exception(
          f'Element not found when executing get_attributes {element_selector}')
    else:
      target_ele_attrs = target_ele.get_attributes()
      target_ele_attrs['text'] = target_ele_attrs.replace('--', ' ')
      return target_ele_attrs

  def back(self):
    global ACTION_COUNT
    '''
    close the current window
    '''

    # get the currently executing code
    code_lines = tools.load_txt_file('tmp/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(f"go back at line {lineno}, code is:{code_lines[lineno - 1]}")
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file('tmp/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file('tmp/combined_code.txt').split(
        '\n')[lineno_in_original_script]

    print(f'try to go back')
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    state_desc = element_tree.str

    ele_data = {
        'xpath': None,
        'api_name': None,
        'text': None,
        'action_type': 'navigate_back',
        'dependencies': None,
        'statement': {
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        }
    }

    self.execute_action(ele_data)

    # todo
    # yaml_path = os.path.join(self.input_policy.device.output_dir,
    #                          f'log_{self.input_manager.task_id}.yaml')
    # _save2yaml(yaml_path,
    #            state_desc,
    #            idx=None,
    #            inputs=None,
    #            action_type='go back',
    #            state_str=old_state.state_str,
    #            structure_str=old_state.structure_str,
    #            tag=old_state.tag,
    #            width=old_state.width,
    #            height=old_state.height,
    #            raw_prompt=None,
    #            raw_answer=None,
    #            currently_executing_code={
    #                'current_code': current_code_line,
    #                'original_lineno': lineno_in_original_script,
    #                'original_code': original_code_line
    #            })
    # current_state = self.input_policy.device.get_current_state()
    # if current_state.get_app_activity_depth(self.input_manager.app) > 0:
    # If the app is in activity stack but is not in foreground

    # ACTION_COUNT += 1
    check_aciton_count()


# def tap(button_api):
#     if button not in current UI:
#         solve button dependency
#     else:
#         tap button
