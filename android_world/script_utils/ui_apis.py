import json
import os
import re
import pdb
import yaml
import inspect
import time

from absl import logging

from android_world.agents.agent_utils import ElementTree, EleAttr
from android_world.agents import agent_utils
from android_world.agents import infer
from android_world.env import interface
from android_world.env import json_action

from android_world.script_utils import tools
from android_world.script_utils.api_doc import ApiDoc

from . import WAIT_AFTER_ACTION_SECONDS, MAX_SCROLL_NUM, MAX_ACTION_COUNT

api_names = [
    'long_tap', 'tap', 'set_text', 'scroll', 'get_text', 'get_attributes',
    'back', 'get_ui_tree', 'check_ele_exist'
]

ACTION_COUNT = 0

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
    script = script.replace(f'.{verifier_instant_name}.{api_name}(', f'.{api_name}(')
  script = script.replace(f'long_{verifier_instant_name}.tap(', 'long_tap(')
  return script, line_mappings


def _save2yaml(file_name,
               state_prompt,
               idx,
               inputs=None,
               action_type='touch',
               api_name=None,
               xpath=None,
               skeleton=None,
               tag=None,
               raw_prompt=None,
               raw_answer=None,
               currently_executing_code=None,
               effect_range='global'):
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
      'api_name': api_name,
      'xpath': xpath,
      'skeleton': skeleton,
      'tag': tag,
      'raw_prompt': raw_prompt,
      'raw_answer': raw_answer,
      'currently_executing_code': currently_executing_code,
      'effect_range': effect_range
  })
  data = {
      'step_num': len(list(old_yaml_data['records'])),
      'records': new_records
  }
  t1 = time.time()
  with open(file_name, 'w', encoding='utf-8') as f:
    yaml.safe_dump(data, f)
  print(f'save to yaml time: {time.time() - t1}')


def save_current_ui_to_log(env: interface.AsyncEnv,
                           save_path: str,
                           api_name: str,
                           xpath: str,
                           currently_executing_code=None):
  log_path = os.path.join(save_path, f'log.yaml')
  state = env.get_state()
  element_tree = agent_utils.forest_to_element_tree(state.forest)
  state_desc = element_tree.str

  if os.path.exists(log_path):
    output_log = tools.load_yaml_file(log_path)
    if len(output_log['records']) == 0:
      return

    last_skeleton_str = output_log['records'][-1]['skeleton']

    skeleton_str = element_tree.skeleton.str
    if skeleton_str != last_skeleton_str:  # todo:: check
      output_log['records'].append({
          'Action': None,
          'Choice': 'crashed',
          'Input': None,
          'api_name': api_name,
          'xpath': xpath,
          'State': state_desc,
          'tag': "todo",  # todo:: initial a state for tag
          'raw_prompt': None,
          'raw_answer': None,
          'currently_executing_code': currently_executing_code
      })
      tools.dump_yaml_file(log_path, output_log)

  else:
    output_log = {
        'step_num':
            0,
        'records': [{
            'Action': None,
            'Choice': 'crashed',
            'Input': None,
            'api_name': api_name,
            'xpath': xpath,
            'State': state_desc,
            'tag': "todo",
            'raw_prompt': None,
            'raw_answer': None,
            'currently_executing_code': currently_executing_code
        }]
    }
    tools.dump_yaml_file(log_path, output_log)


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


class Verifier:

  def __init__(self, env: interface.AsyncEnv, save_path: str, app_name: str,
               api_xpaths, doc: ApiDoc) -> None:
    # android world
    self.env = env
    self.save_path = save_path
    self.app_name = app_name
    self.api_xpaths = api_xpaths
    self.doc = doc
    # autodroid
    self.last_screen_html_str = None

  def get_action_from_xpath(self, element_tree: ElementTree, api_name: str,
                            xpath: str, action_type: str, input_text: str,
                            statement):

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
    file_path = os.path.join(self.save_path, 'log.yaml')
    _save2yaml(
        file_path,
        element_tree.str,
        ele.id,
        input_text,
        action_type,
        api_name,
        xpath,
        element_tree.skeleton.str,
        "",  # todo::
        None,
        None,
        currently_executing_code=statement)

    return agent_utils.convert_action(action_type, ele, input_text)

  def scroll_and_find_target_ele(self,
                                 element_tree: ElementTree,
                                 api_name: str,
                                 xpath,
                                 action_type,
                                 text,
                                 statement,
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

        target_action = self.get_action_from_xpath(element_tree, api_name,
                                                   xpath, action_type, text,
                                                   statement)
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

        target_ele = element_tree.get_ele_by_properties(
            ele_properties_without_idx)

        file_path = os.path.join(self.save_path, f'log.yaml')

        _save2yaml(
            file_path,
            element_tree.str,
            target_ele.id if target_ele else None,
            api_name,
            f'scroll {direction}',
            api_name=None,
            xpath=xpath,
            skeleton=element_tree.skeleton.str,
            tag="",  # todo
            currently_executing_code=statement)

        if target_ele:
          dir = direction.lower()
          self.env.execute_action(
              json_action.JSONAction(
                  **{
                      "action_type": "scroll",
                      "index": target_ele.local_id,
                      "direction": dir
                  }))
          time.sleep(WAIT_AFTER_ACTION_SECONDS)
    return {"action_type": "status", "goal_status": "infeasible"}

  def execute_action(self, ele_data: dict):
    global ACTION_COUNT

    logging.info(f'execute action: {ele_data}')
    api_name = ele_data['api_name']
    # if not api_name:
    #   return

    if ACTION_COUNT == 0:
      self.env.execute_action(
          json_action.JSONAction(**{
              "action_type": "open_app",
              "app_name": self.app_name
          }))
      time.sleep(WAIT_AFTER_ACTION_SECONDS)

    code_to_be_executed = ele_data

    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    # first execute the code
    xpath = code_to_be_executed['xpath']
    action_type = code_to_be_executed['action_type']
    text = code_to_be_executed['text']

    if action_type == None:
      return

    executable_action = self.get_action_from_xpath(
        element_tree, api_name, xpath, action_type, text,
        code_to_be_executed['statement'])

    if executable_action.get('goal_status', None) != 'infeasible':
      self.env.execute_action(json_action.JSONAction(**executable_action))
      time.sleep(WAIT_AFTER_ACTION_SECONDS)
      return

    # could not find a target element in the current UI, find in the dependencies
    executable_action = self.scroll_and_find_target_ele(
        element_tree, api_name, xpath, action_type, text,
        code_to_be_executed['statement'])

    # could not find a target element in the current UI, find in the dependencies
    if executable_action.get('goal_status', None) != 'infeasible':
      self.env.execute_action(json_action.JSONAction(**executable_action))
      time.sleep(WAIT_AFTER_ACTION_SECONDS)
      return

    ## dependency
    # we have executed all the dependencies, but still not found the target element
    done = False
    while not done:  # todo:: limit the max number of retry
      state = self.env.get_state()
      element_tree = agent_utils.forest_to_element_tree(state.forest)
      current_skeleton = element_tree.skeleton
      _, dependency_action = self.doc.get_dependency(current_skeleton, api_name) # todo:: which priority is higher compared the skeleton and the screen_name

      if not dependency_action:
        break
      
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
          if current_skeleton != current_skeleton.extract_common_skeleton(
              target_skeleton):
            if is_match:
              break
            else:
              continue

          action_type = action.action_type
          text = action.text
          xpath = self.doc.get_xpath_by_name(_screen_name, action.api_name)
          executable_action = self.get_action_from_xpath(
              element_tree, api_name, xpath, action_type, text,
              code_to_be_executed['statement'])

          if executable_action.get('goal_status', None) == 'infeasible':
            if is_match:
              break
            else:
              continue

          # execute the action
          is_match = True
          dep_id = idx
          self.env.execute_action(json_action.JSONAction(**executable_action))
          time.sleep(WAIT_AFTER_ACTION_SECONDS)

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
    output_log = tools.load_yaml_file(os.path.join(self.save_path, f'log.yaml'))
    if output_log['records'][-1]['Choice'] == 'crashed':
      raise Exception(f'Action not found when executing tap {api_name}')

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
          'api_name': element_selector_api_name,
          'text': None,
          'action_type': None,
          'statement': statement
      }

      self.execute_action(ele_data)
      self.check_output_crash(element_selector_xpath)
      state = self.env.get_state()
      element_tree = agent_utils.forest_to_element_tree(state.forest)
      target_ele = element_tree.get_ele_by_xpath(element_selector_xpath)

    _save2yaml(
        file_name=os.path.join(self.save_path, f'log.yaml'),
        state_prompt=element_tree.str,
        idx=target_ele.id if target_ele else None,
        inputs=None,
        action_type=caller_type,
        api_name=element_selector_api_name,
        xpath=element_selector_xpath,
        skeleton=element_tree.skeleton.str,
        tag="todo",  # todo::
        raw_prompt=None,
        raw_answer=None,
        currently_executing_code=statement)
    return target_ele, element_tree

  def _save_getting_info_action(self, action_type, api_name, xpath,
                                current_code_line, lineno_in_original_script,
                                original_code_line):
    yaml_path = os.path.join(self.save_path, 'log.yaml')
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    state_desc = element_tree.str
    _save2yaml(
        yaml_path,
        state_desc,
        idx=None,
        inputs=None,
        action_type=action_type,
        api_name=api_name,
        xpath=xpath,
        skeleton=element_tree.skeleton.str,
        tag="todo",  # todo::
        raw_prompt=None,
        raw_answer=None,
        currently_executing_code={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        })

  def get_ui_tree(self):
    '''
        return the current UI tree as a string.
        '''
    global ACTION_COUNT
    if ACTION_COUNT == 0:
      self.env.execute_action(  # maybe it's unnecessary
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

  def check_last_screen_html_is_same(self):
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    current_screen_html_str = element_tree.str
    is_same = False
    if not self.last_screen_html_str:
      self.last_screen_html_str = current_screen_html_str
    else:
      is_same = self.last_screen_html_str == current_screen_html_str
      self.last_screen_html_str = current_screen_html_str

    return is_same

  def tap(self, button_api):
    global ACTION_COUNT
    # get the currently executing code
    code_lines = tools.load_txt_file(f'{self.save_path}/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"Tap: {button_api} at line {lineno}, code is:{code_lines[lineno - 1]}")
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file(f'{self.save_path}/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file(f'{self.save_path}/code.txt').split(
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
    self.check_last_screen_html_is_same()
    # ACTION_COUNT += 1
    check_aciton_count()

  def long_tap(self, button_api):
    global ACTION_COUNT
    # get the currently executing code
    code_lines = tools.load_txt_file(f'{self.save_path}/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"long tap: {button_api} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file(f'{self.save_path}/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file(f'{self.save_path}/code.txt').split(
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
    self.check_last_screen_html_is_same()
    # ACTION_COUNT += 1
    check_aciton_count()

  def set_text(self, text_api, text):
    global ACTION_COUNT
    # get the currently executing code
    code_lines = tools.load_txt_file(f'{self.save_path}/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"settext: {text_api} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file(f'{self.save_path}/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file(f'{self.save_path}/code.txt').split(
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
    self.check_last_screen_html_is_same()
    # ACTION_COUNT += 1
    check_aciton_count()

  def scroll(self, scroller_api, direction):
    global ACTION_COUNT
    # get the currently executing code
    code_lines = tools.load_txt_file(f'{self.save_path}/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"scroll {direction}: {scroller_api} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file(f'{self.save_path}/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file(f'{self.save_path}/code.txt').split(
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
    is_to_bottom = self.check_last_screen_html_is_same()
    # ACTION_COUNT += 1
    check_aciton_count()
    return is_to_bottom

  def get_text(self, element_selector):
    global ACTION_COUNT
    '''
    return the text of the element as a string.
    '''

    # get the currently executing code
    code_lines = tools.load_txt_file(f'{self.save_path}/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"get_text: {element_selector} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file(f'{self.save_path}/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file(f'{self.save_path}/code.txt').split(
        '\n')[lineno_in_original_script]

    target_ele, element_tree = self.navigate_and_get_target_element(
        element_selector,
        caller_type='get_text',
        statement={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        })

    self._save_getting_info_action('get_text', None, None, current_code_line,
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
    code_lines = tools.load_txt_file(f'{self.save_path}/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"get_attributes: {element_selector} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file(f'{self.save_path}/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file(f'{self.save_path}/code.txt').split(
        '\n')[lineno_in_original_script]

    target_ele, _ = self.navigate_and_get_target_element(
        element_selector,
        caller_type='get_attributes',
        statement={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        })

    yaml_path = os.path.join(self.save_path, f'log.yaml')
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    state_desc = element_tree.str
    _save2yaml(
        yaml_path,
        state_desc,
        idx=None,
        inputs=None,
        action_type='get_attributes',
        api_name=element_selector,
        xpath=None,
        skeleton=element_tree.skeleton.str,
        tag="todo",
        raw_prompt=None,
        raw_answer=None,
        currently_executing_code={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        })
    self._save_getting_info_action('get_attributes', None, None,
                                   current_code_line, lineno_in_original_script,
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
    code_lines = tools.load_txt_file(f'{self.save_path}/compiled_code.txt').split('\n')
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(f"go back at line {lineno}, code is:{code_lines[lineno - 1]}")
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file(f'{self.save_path}/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file(f'{self.save_path}/code.txt').split(
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
    yaml_path = os.path.join(self.save_path, f'log.yaml')
    _save2yaml(
        yaml_path,
        state_desc,
        idx=None,
        inputs=None,
        action_type='go back',
        api_name=None,
        xpath=None,
        skeleton=element_tree.skeleton.str,
        tag="todo",
        raw_prompt=None,
        raw_answer=None,
        currently_executing_code={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        })
    # current_state = self.input_policy.device.get_current_state()
    # if current_state.get_app_activity_depth(self.input_manager.app) > 0:
    # If the app is in activity stack but is not in foreground

    self.check_last_screen_html_is_same()
    # ACTION_COUNT += 1
    check_aciton_count()


class ElementList:

  def __init__(self, api_name, api_xpath, env: interface.AsyncEnv,
               save_path: str, api_xpaths: dict[str, str],
               verifier: Verifier) -> None:
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

  def _save_getting_info_action(self, action_type, api_name: str, xpath: str,
                                current_code_line, lineno_in_original_script,
                                original_code_line):
    yaml_path = os.path.join(self.save_path, f'log.yaml')
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    state_desc = element_tree.str

    _save2yaml(
        yaml_path,
        state_desc,
        idx=None,
        inputs=None,
        action_type=action_type,
        api_name=api_name,
        xpath=xpath,
        skeleton=element_tree.skeleton.str,
        tag="todo",  # todo::
        raw_prompt=None,
        raw_answer=None,
        currently_executing_code={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        },
        effect_range=self.api_name)

  def check_api_name(self, api_name):
    if api_name not in self.api_xpaths.keys():  # not found xpath
      # find the first line with the api_name in the original script (combined with the preparation, this is to stay the same with tap, set_text, etc.)
      code_lines = tools.load_txt_file(f'{self.save_path}/compiled_code.txt').split('\n')
      # lines = original_script.split('\n')
      line_with_api_name = None
      for line_num, line in enumerate(code_lines):
        if api_name in line:
          line_with_api_name = line.strip()
          lineno_in_original_script = tools.load_json_file(
              f'{self.save_path}/line_mappings.json')[str(line_num)]
          original_code_line = tools.load_txt_file(
              f'{self.save_path}/code.txt').split('\n')[lineno_in_original_script]
          break
      currently_executing_code = {
          'current_code': line_with_api_name,
          'original_lineno': lineno_in_original_script,
          'original_code': original_code_line
      }

      save_current_ui_to_log(
          self.env,
          self.save_path,
          api_name,
          None,
          currently_executing_code=currently_executing_code)
      raise Exception(
          f'Error: Element {api_name} does not exist in the app! Please use the real element name! '
      )

  def convert_ele_attr_to_elementlist(self, ele_attr):
    ele_xpath = f"//{ele_attr.type_}[@id='{ele_attr.id}']"
    elementlist = ElementList(
        api_name=None,
        api_xpath=ele_xpath,
        env=self.env,
        save_path=self.save_path,
        api_xpaths=self.api_xpaths,
        verifier=self.verifier)
    return ele_xpath, elementlist

  def navigate_to_api_name(self, api_name, caller_type,
                           statement):  # todo:: check
    # if the api_name is provided, then the element_list is selected from the api document, then we should check its dependency
    if api_name:
      target_ele, element_tree = self.verifier.navigate_and_get_target_element(
          api_name, caller_type, statement)
      if not target_ele:
        logging.error(f'Element {api_name} not found! ')
        raise Exception(f'Element {api_name} not found! ')

  def __getitem__(self, selector):
    global ACTION_COUNT

    # get the currently executing code
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, '__getitem__', selector)

    self.navigate_to_api_name(
        self.api_name,
        caller_type='index',
        statement={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        })
    # todo:: refactor this part to the initial function
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    target_ele_group = element_tree.get_ele_by_xpath(self.element_list_xpath)

    # Default to integer index if not a custom selector
    if isinstance(selector, int):
      ele_attr = element_tree.get_children_by_idx(target_ele_group, selector)
      matched_xpath, matched_ele = self.convert_ele_attr_to_elementlist(
          ele_attr)
      self._save_getting_ele_info_action_to_yaml(
          'index', self.api_name, f'{self.api_name}[{selector}]', matched_xpath)
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
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, '__next__', self.api_name)
    self._save_getting_info_action('index', self.api_name,
                                   self.element_list_xpath, current_code_line,
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
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'match', match_data)

    self._save_getting_info_action('match', self.api_name,
                                   self.element_list_xpath, current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)

    self.navigate_to_api_name(
        self.api_name,
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
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, '__len__', self.api_name)
    
    self._save_getting_info_action('len', self.api_name,
                                   self.element_list_xpath, current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)

    self.navigate_to_api_name(
        self.api_name,
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

  def _save_getting_ele_info_action_to_yaml(self, action_type, api_name,
                                            action_statement, matched_xpath):
    '''
      @action_type: match/index/len
      @action_statement: the statement of the action, such as "open_note_title_list[0]"
      @matched_xpath: the xpath of the matched element
      '''
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    state_desc = element_tree.get_str(is_color=False)

    statement = f'{action_statement} -> {matched_xpath}'

    yaml_path = os.path.join(self.save_path, f'log.yaml')
    _save2yaml(
        yaml_path,
        state_desc,
        idx=None,
        inputs=None,
        action_type=action_type,
        api_name=api_name,
        xpath=matched_xpath,
        skeleton=element_tree.skeleton.str,
        tag="todo",
        raw_prompt=None,
        raw_answer=None,
        currently_executing_code=statement)

  def get_current_code_line(self, lineno: int, action: str, element_selector_name: str):
    # get the currently executing code
    code_lines = tools.load_txt_file(f'{self.save_path}/compiled_code.txt').split('\n')
    print(
        f"{action}: {element_selector_name} at line {lineno}, code is:{code_lines[lineno - 1]}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = int(
        tools.load_json_file(f'{self.save_path}/line_mappings.json')[str(lineno - 1)])
    original_code_line = tools.load_txt_file(f'{self.save_path}/code.txt').split(
        '\n')[lineno_in_original_script]

    return current_code_line, lineno_in_original_script, original_code_line

  def find_target_element(self, element_selector_xpath: str):
    
    target_ele = None
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    target_ele_group = element_tree.get_ele_by_xpath(self.element_list_xpath)
    if target_ele_group:
      subtree = element_tree.extract_subtree(target_ele_group.id)
      if subtree:
        target_ele = subtree.get_ele_by_xpath(element_selector_xpath)

    return target_ele
    
  def tap(self, button_api):
    global ACTION_COUNT

    if isinstance(button_api, str):
      print(f'try to tap: {button_api}, current action account: {ACTION_COUNT}')
      button_api_name = button_api.split('$')[-1]
      button_api_xpath = self.api_xpaths[button_api_name]
    elif isinstance(button_api, ElementList):
      button_api_name = button_api.api_name if button_api.api_name else button_api.element_list_xpath
      button_api_xpath = button_api.element_list_xpath
    else:
      raise Exception(
          f'Error: button_api type is not supported: {type(button_api)}')

    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'touch', button_api_name)
    self._save_getting_info_action('touch', button_api_name,
                                   button_api_xpath, current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)
    
    target_ele = self.find_target_element(button_api_xpath)

    if not target_ele:
      raise Exception(f'{button_api_name} not found in {self.api_name} ')

    converted_action = agent_utils.convert_action("touch", target_ele, "")
    if converted_action.get('goal_status', None) == 'infeasible':
      raise Exception(f'Error: {button_api_name} is infeasible! ')
    
    self.env.execute_action(json_action.JSONAction(**converted_action))
    time.sleep(WAIT_AFTER_ACTION_SECONDS)
    
    self.verifier.check_output_crash(button_api_name)
    # ACTION_COUNT += 1
    check_aciton_count()

  def long_tap(self, button_api):
    global ACTION_COUNT
    
    if isinstance(button_api, str):
      print(f'try to long_tap: {button_api}, current action account: {ACTION_COUNT}')
      button_api_name = button_api.split('$')[-1]
      button_api_xpath = self.api_xpaths[button_api_name]
    elif isinstance(button_api, ElementList):
      button_api_name = button_api.api_name if button_api.api_name else button_api.element_list_xpath
      button_api_xpath = button_api.element_list_xpath
    else:
      raise Exception(
          f'Error: button_api type is not supported: {type(button_api)}')

    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'long_touch', button_api_name)
    self._save_getting_info_action('long_touch', button_api_name,
                                   button_api_xpath, current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)
    
    target_ele = self.find_target_element(button_api_xpath)

    if not target_ele:
      raise Exception(f'{button_api_name} not found in {self.api_name} ')

    converted_action = agent_utils.convert_action("long_touch", target_ele, "")
    if converted_action.get('goal_status', None) == 'infeasible':
      raise Exception(f'Error: {button_api_name} is infeasible! ')
    
    self.env.execute_action(json_action.JSONAction(**converted_action))
    time.sleep(WAIT_AFTER_ACTION_SECONDS)
    
    self.verifier.check_output_crash(button_api_name)
    # ACTION_COUNT += 1
    check_aciton_count()

  def set_text(self, input_api, text):
    global ACTION_COUNT

    if isinstance(input_api, str):
      input_api_name = input_api.split('$')[-1]
      input_api_xpath = self.api_xpaths[input_api_name] # todo:: if multiple, we can try step by step
    elif isinstance(input_api, ElementList):
      input_api_name = input_api.api_name if input_api.api_name else input_api.element_list_xpath
      input_api_xpath = input_api.element_list_xpath
    else:
      raise Exception(
          f'Error: input_api type is not supported: {type(input_api)}')
    
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'set_text', input_api_name)
    self._save_getting_info_action('set_text', input_api_name,
                                   input_api_xpath, current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)
    
    target_ele = self.find_target_element(input_api_xpath)

    if not target_ele:
      raise Exception(f'{input_api_name} not found in {self.api_name} ')

    converted_action = agent_utils.convert_action("set_text", target_ele, text)
    if converted_action.get('goal_status', None) != 'infeasible':
      raise Exception(f'Error: {input_api_name} is infeasible! ')
    
    self.env.execute_action(json_action.JSONAction(**converted_action))
    time.sleep(WAIT_AFTER_ACTION_SECONDS)
    
    self.verifier.check_output_crash(input_api_name)
    # ACTION_COUNT += 1
    check_aciton_count()

  def get_text(self, element_selector):
    global ACTION_COUNT
    '''
    return the text of the element as a string.
    '''

    if isinstance(element_selector, str):
      element_selector = element_selector.split('$')[-1]
      element_selector_xpath = self.api_xpaths[element_selector]
      element_selector_api_name = element_selector
    elif isinstance(element_selector, ElementList):
      element_selector_xpath = element_selector.element_list_xpath
      element_selector_api_name = element_selector.api_name if element_selector.api_name else element_selector.element_list_xpath
    else:
      raise Exception(
          f'Error: element_selector type is not supported: {type(element_selector)}')

    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'get_text', element_selector_api_name)
    self._save_getting_info_action('get_text', element_selector_api_name,
                                   element_selector_xpath, current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)
    
    target_ele = self.find_target_element(element_selector_xpath)

    if not target_ele:
      raise Exception(f'{element_selector_api_name} not found in {self.api_name} ')
    
    check_aciton_count()

    if not target_ele:
      raise Exception(
          f'Element not found when executing get_text {element_selector}')
    else:
      text = target_ele.text if target_ele.text else ''
      text = text.replace('--', ' ')
      return text

  def get_attributes(self, element_selector):
    global ACTION_COUNT
    '''
    return the attributes of the element as a dict, dict keys include "selected", "checked", "scrollable", dict values are boolean. eg. get_attributes($files[3])["selected"].
    '''
    if isinstance(element_selector, str):
      element_selector = element_selector.split('$')[-1]
      element_selector_xpath = self.api_xpaths[element_selector]
      element_selector_api_name = element_selector
    elif isinstance(element_selector, ElementList):
      element_selector_xpath = element_selector.element_list_xpath
      element_selector_api_name = element_selector.api_name if element_selector.api_name else element_selector.element_list_xpath
    else:
      raise Exception(
          f'Error: element_selector type is not supported: {type(element_selector)}')

    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'get_attributes', element_selector_api_name)
    self._save_getting_info_action('get_attributes', element_selector_api_name,
                                   element_selector_xpath, current_code_line,
                                   lineno_in_original_script,
                                   original_code_line)
    
    target_ele = self.find_target_element(element_selector_xpath)

    if not target_ele:
      raise Exception(f'{element_selector_api_name} not found in {self.api_name} ')
    
    check_aciton_count()
    if not target_ele:
      raise Exception(
          f'Element not found when executing get_attributes {element_selector}')
    else:
      target_ele_attrs = target_ele.get_attributes()
      target_ele_attrs['text'] = target_ele_attrs.replace('--', ' ')
      return target_ele_attrs
  
  def scroll(self, scroller_api, direction):
    return self.verifier.scroll(scroller_api, direction)

  def back(self):
    self.verifier.back()
