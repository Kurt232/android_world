import json
import os
import re
import pdb
import yaml
import inspect
import time
import numpy as np
import datetime

from absl import logging

from android_world.agents.agent_utils import ElementTree, EleAttr
from android_world.agents import agent_utils
from android_world.env import interface
from android_world.env import json_action

from android_world.script_utils import tools
from android_world.script_utils.api_doc import ApiDoc
from android_world.script_utils.err import XPathError, APIError, ActionError, NotFoundError

from . import WAIT_AFTER_ACTION_SECONDS, MAX_SCROLL_NUM, MAX_ACTION_COUNT, IS_LOG_SCREENSHOT, MAX_DEPENDENCE_DEPTH, MAX_DEPENDENCE_WIDTH

api_names = [
    'long_tap', 'tap', 'set_text', 'scroll', 'get_text', 'get_attributes',
    'back', 'get_ui_tree', 'check_ele_exist'
]

def sanitize_name(name):
  # To make it a valid python variable, replace all non-word characters with '_', and replace the first digit with '_'
  return re.sub(r'\W|^(?=\d)', '_', name)

  
def regenerate_script(script, verifier_instant_name):
  '''
    find element_lists and instantiate them, remove '$' from element_selectors, add instant_name prefix to all apis
    '''
  pattern = re.compile(r'^.*?\$([\w%]+).*?(\[\d+\]|\.match\([^)]+\)).*$',
                       re.MULTILINE)
  script_lines = script.split('\n')
  modified_lines = [
      f'def autodroidv2_task_solution_code({verifier_instant_name}):'
  ]  # def a function because of the necessity of inspecting the script
  all_appeared_api_names = []
  line_mappings = {}  # key: compiled script line number, value: original script line number
  element_statement_set = set()
  
  for _, line in enumerate(script_lines):
    match = pattern.match(line)
    if match:
      # for matching, indexing operation statements.
      element_name = match.group(1)
      sanitized_element_name = sanitize_name(element_name)
      line = line.replace(f'${element_name}', sanitized_element_name)
      
      element_statement_set.add(f'{sanitized_element_name} = ElementList(\'{element_name}\', None, {verifier_instant_name})')
    else:
      # for tapping, set_text, etc. statements
      api_name_pattern = r'\$([\w%]+)'  # also match apis with %, for example, font_size_150%
      matches = re.findall(api_name_pattern, line)
      if matches:
        for api_name in matches:
          sanitized_api_name = sanitize_name(api_name)
          if sanitized_api_name not in all_appeared_api_names:
            all_appeared_api_names.append(api_name)
            element_statement_set.add(f'{sanitized_api_name} = ElementList(\'{api_name}\', None, {verifier_instant_name})')

          line = line.replace(f'${api_name}', sanitized_api_name)

    modified_lines.append(f'\t{line}')
  
  element_statement_list = list(element_statement_set)
  element_statement_list.sort()
  statement_len = len(element_statement_list)
  beginning_tabs = tools.get_leading_tabs(modified_lines[1])
  
  for s in element_statement_list:
    modified_lines.insert(1, beginning_tabs + s)
  
  for i, _ in enumerate(modified_lines[statement_len + 1:]):
    original_line_num = i
    compiled_line_num = i + statement_len + 1
    line_mappings[compiled_line_num] = original_line_num

  modified_lines.append(
      f'autodroidv2_task_solution_code({verifier_instant_name})'
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
               target='action',
               effect_range='global'):
  if not os.path.exists(file_name):
    tmp_data = {'step_num': 0, 'records': []}
    with open(file_name, 'w', encoding='utf-8') as f:
      yaml.dump(tmp_data, f)

  with open(file_name, 'r', encoding='utf-8') as f:
    old_yaml_data = yaml.safe_load(f)
  new_records = old_yaml_data['records']
  new_records.append({
      'step': len(new_records),
      'State': state_prompt,
      'Choice': idx,
      'Action': action_type,
      'Input': inputs,
      'api_name': api_name,
      'xpath': xpath,
      'skeleton': skeleton,
      'tag': tag,
      'target': target,
      'raw_prompt': raw_prompt,
      'raw_answer': raw_answer,
      'currently_executing_code': currently_executing_code,
      'effect_range': effect_range
  })
  data = {
      'step_num': len(new_records),
      'records': new_records
  }
  t1 = time.time()
  with open(file_name, 'w', encoding='utf-8') as f:
    yaml.safe_dump(data, f)
  print(f'save to yaml time: {time.time() - t1}')

def _save2log(save_path, 
               log_file: str,
               element_tree: ElementTree = None,
               idx=None,
               inputs=None,
               action_type='touch',
               api_name=None,
               xpath=None,
               currently_executing_code=None,
               comment: str = 'action',
               effect_range: str = 'global',
               screenshot: np.ndarray = None):
  
  timestamp = datetime.datetime.now().strftime('%Y-%m-%d_T%H%M%S')
  _save2yaml(
    file_name=log_file,
    state_prompt=element_tree.str if element_tree else None,
    idx=idx,
    inputs=inputs,
    action_type=action_type,
    api_name=api_name,
    xpath=xpath,
    skeleton=element_tree.skeleton.str if element_tree else None,
    tag=timestamp,
    raw_prompt=None,
    raw_answer=None,
    currently_executing_code=currently_executing_code,
    target=comment,
    effect_range=effect_range
  )
  
  if IS_LOG_SCREENSHOT and screenshot is not None:
    agent_utils.save_screenshot(save_path, timestamp, screenshot)


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


class CodeConfig:
  def __init__(self, 
               app_name: str, 
               doc: ApiDoc, 
               save_path: str, 
               code: str, 
               compiled_code: str, 
               line_mappings: dict[int, int]):
    self.app_name = app_name
    self.doc = doc
    self.save_path = save_path
    self.log_file = save_path + '/log.yaml'
    self.code = code
    self.compiled_code = compiled_code
    self.line_mappings = line_mappings
    self.code_lines = code.split('\n')
    self.compiled_code_lines = compiled_code.split('\n')


class CodeStatus:
  def __init__(self):
    # internal
    self.action_count = 0
    self.last_screen_html_str = None
    
  def reset(self):
    self.action_count = 0
    self.last_screen_html_str = None
    
  def check_action_count(self):
    if self.action_count >= MAX_ACTION_COUNT:
      # raise Exception(f'Action count is over {MAX_ACTION_COUNT}, the script may be in an infinite loop')
      pass
    self.action_count += 1
  
  def check_last_screen(self, screen_html_str: str):
    is_same = False
    if not self.last_screen_html_str:
      self.last_screen_html_str = screen_html_str
    else:
      is_same = self.last_screen_html_str == screen_html_str
      self.last_screen_html_str = screen_html_str
    return is_same


class Verifier:

  def __init__(self, env: interface.AsyncEnv, config: CodeConfig, status: CodeStatus) -> None:
    # android world
    self.env = env
    self.save_path: str = config.save_path
    self.app_name: str = config.app_name
    self.doc: ApiDoc = config.doc
    self.api_xpaths = self.doc.api_xpath
    self.config = config
    
    # status
    self.status = status
    
    self._state = None
    self._element_tree = None
  
  @property
  def state(self):
    if not self._state:
      self._state = self.env.get_state(True)
    return self._state

  @property
  def element_tree(self):
    if not self._element_tree:
      self._element_tree = agent_utils.forest_to_element_tree(self.state.forest, self.env.logical_screen_size)
    return self._element_tree
  
  def update_state(self):
    self._state = self.env.get_state(True)
    self._element_tree = agent_utils.forest_to_element_tree(self._state.forest, self.env.logical_screen_size)
  
  @property
  def action_count(self):
    return self.status.action_count

  def check_action_count(self):
    self.status.check_action_count()
  
  @property
  def last_screen(self):
    return self.status.last_screen_html_str
  
  def check_last_screen_html(self):
    is_same = self.status.check_last_screen(self.element_tree.str)
    return is_same

  def scroll_and_find_target_ele(self,
                                 xpath,
                                 statement,
                                 direction='DOWN'):
    all_ele_descs_during_scrolling = []

    element_tree = self.element_tree
    for ele_id in element_tree.scrollable_ele_ids:
      origin_ele = element_tree.ele_map[ele_id]
      ele_properties_without_idx = {
          'resource_id': origin_ele.resource_id,
          'class_name': origin_ele.class_name,
          'content_description': origin_ele.content_description,
          'bound_box': origin_ele.bound_box,
      }

      for _ in range(MAX_SCROLL_NUM):
        state = self.state
        element_tree = self.element_tree
        target_ele = element_tree.get_ele_by_xpath(xpath)
        
        if target_ele:
          return target_ele
        
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

        _save2log(
          save_path=self.save_path,
          log_file=self.config.log_file,
          element_tree=element_tree,
          idx=target_ele.id if target_ele else None,
          inputs=None,
          action_type=f'scroll {direction}',
          api_name=None,
          xpath=xpath,
          currently_executing_code=statement,
          comment='navigate',
          screenshot=state.pixels.copy())

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
          self.update_state()
          is_same = self.check_last_screen_html()
          if is_same:
            break
    return None

  def execute_action(self, ele_data: dict):
    logging.info(f'execute action: {ele_data}')
    code_to_be_executed = ele_data

    state = self.state
    element_tree = self.element_tree
    # first execute the code
    api_name = code_to_be_executed['api_name']
    
    xpath = code_to_be_executed['xpath']
    action_type = code_to_be_executed['action_type']
    text = code_to_be_executed['text']
    statement = code_to_be_executed['statement']
    
    # try find the target element in the current UI
    target_ele = element_tree.get_ele_by_xpath(xpath)
    
    # avoid the target element is in the bottom of the screen
    if action_type == 'set_text' and target_ele:
      _, y = target_ele.ele.bbox_pixels.center
      width, height = self.env.logical_screen_size
      
      if y >= 0.9 * height:
        _save2log(
            save_path=self.save_path,
            log_file=self.config.log_file,
            element_tree=element_tree,
            idx=target_ele.id,
            inputs=text,
            action_type='scroll down',
            api_name=None,
            xpath=None,
            currently_executing_code=statement,
            comment='navigate',
            screenshot=state.pixels.copy())
        self.env.execute_action(
            json_action.JSONAction(**{
                "action_type": "scroll",
                "index": target_ele.local_id, # scroll down target element
                "direction": 'down' # it happens nothing when it is not scrollable
            }))
        time.sleep(WAIT_AFTER_ACTION_SECONDS)
        self.update_state()
        self.check_last_screen_html()
        element_tree = self.element_tree
        target_ele = element_tree.get_ele_by_xpath(xpath)
      
    if not target_ele:
      # find the target element in the scroll down views
      target_ele = self.scroll_and_find_target_ele(xpath, statement)

      # could not find a target element in the current UI, find in the dependencies
      if not target_ele:
        state = self.state
        element_tree = self.element_tree
        
        if api_name:
          is_in_current_screen = self.doc.check_api_name_in_current_screen(api_name, element_tree.skeleton)
          if is_in_current_screen:
            # assume the target element is in the current screen
            # but we still can't find it, so raise an error
            raise XPathError(f'Not Exist {api_name}[{xpath}]', api_name, xpath)
          # else:
          # not in screen, try to navigate to the screen
        
        ## navigating in dependency
        # we have executed all the dependencies, but still not found the target element
        counter = 0
        while target_ele is None and counter < MAX_DEPENDENCE_WIDTH:
          _, dependency_action = self.doc.get_dependency(api_name)
          
          if not dependency_action:
            break
          
          count = 0
          for action_list in dependency_action[:MAX_DEPENDENCE_DEPTH]:
            count += 1

            is_match = False
            dep_id = -1
            for idx, action in enumerate(reversed(action_list)):
              state = self.state
              element_tree = self.element_tree
              
              # try to find the target element in the current UI
              target_ele = element_tree.get_ele_by_xpath(xpath)
              if target_ele:
                break
              
              current_screen_name = self.doc.get_screen_name_by_skeleton(element_tree.skeleton)
              if action.screen_name != current_screen_name:
                continue
              
              if action.action_type == 'back':
                self.env.execute_action(
                    json_action.JSONAction(**{
                        "action_type": "navigate_back"
                    }))
                time.sleep(WAIT_AFTER_ACTION_SECONDS)
                self.update_state()
                self.check_last_screen_html()
                is_match = True
                continue
              
              _action_xpath = self.doc.api_xpath.get(action.name, None)
              if not _action_xpath:
                continue
              _target_ele = self.scroll_and_find_target_ele(_action_xpath, statement)
              
              if not _target_ele:
                if is_match:
                  break
                else:
                  continue

              # execute the action
              is_match = True
              dep_id = idx
              _save2log(
                save_path=self.save_path,
                log_file=self.config.log_file,
                element_tree=element_tree,
                idx=_target_ele.id if _target_ele else None,
                inputs=None,
                action_type=action.action_type,
                api_name=action.api_name,
                xpath=_action_xpath,
                currently_executing_code=statement,
                comment='navigate',
                screenshot=state.pixels.copy())
              
              executable_action = agent_utils.convert_action(action.action_type, _target_ele, action.text)
              # finding dependency can tolerate the action error
              # if executable_action.get('action_type') == 'wait':
              #   raise ActionError(f'Fail to {action.action_type}({action.api_name})', None, None, action.action_type, action.api_name)
              self.env.execute_action(json_action.JSONAction(**executable_action))
              time.sleep(WAIT_AFTER_ACTION_SECONDS)
              self.update_state()
              self.check_last_screen_html()

            if dep_id >= len(action_list) - 1:
              state = self.state
              element_tree = self.element_tree
              target_ele = element_tree.get_ele_by_xpath(xpath)              
              break
              # if target_ele is None, continue to find the next dependency
            
            # executed action and changed the screen, we need to find new dependency
            if is_match:
              break

          if count == len(dependency_action):
            # fail to solve the dependency
            # target_ele still is None
            break
          
          counter += 1
      
    if target_ele:
      _save2log(
          save_path=self.save_path,
          log_file=self.config.log_file,
          element_tree=element_tree,
          idx=target_ele.id if target_ele else None,
          inputs=text,
          action_type=action_type,
          api_name=api_name,
          xpath=xpath,
          currently_executing_code=statement,
          comment='action' if action_type else 'navigate',
          screenshot=state.pixels.copy())
      if not action_type: # navigating
        return
      
      executable_action = agent_utils.convert_action(action_type, target_ele, text)
      if executable_action.get('action_type') == 'wait':
        raise ActionError(f'Fail to {action_type}({api_name})', None, None, action_type, api_name)
      self.env.execute_action(json_action.JSONAction(**executable_action))
      time.sleep(WAIT_AFTER_ACTION_SECONDS)
      self.update_state()
      self.check_last_screen_html()
    else:
      _save2log(
          save_path=self.save_path,
          log_file=self.config.log_file,
          element_tree=element_tree,
          idx=None,
          inputs=text,
          action_type=action_type,
          api_name=api_name,
          xpath=xpath,
          currently_executing_code=statement,
          comment='crashed',
          screenshot=state.pixels.copy())
      
      if action_type: # only action can crash
        raise NotFoundError(f'Not found {api_name}[{xpath}]', api_name, xpath)
    return

  def navigate_and_get_target_element(self, element_selector_api_name, element_selector_xpath, caller_type,
                                      statement):
    state = self.state
    element_tree = self.element_tree
    
    target_ele = element_tree.get_ele_by_xpath(element_selector_xpath)
    
    _save2log(
        save_path=self.save_path,
        log_file=self.config.log_file,
        element_tree=element_tree,
        idx=target_ele.id if target_ele else None,
        inputs=None,
        action_type=caller_type,
        api_name=element_selector_api_name,
        xpath=element_selector_xpath,
        currently_executing_code=statement,
        comment='action',
        screenshot=state.pixels.copy())
    
    if not target_ele:
      ele_data = {
          'xpath': element_selector_xpath,
          'api_name': element_selector_api_name,
          'text': None,
          'action_type': None, # navigating
          'statement': statement
      }

      self.execute_action(ele_data)
      state = self.state
      element_tree = self.element_tree
      target_ele = element_tree.get_ele_by_xpath(element_selector_xpath)

      if not target_ele:
        raise NotFoundError(f'Not found {element_selector_api_name}[{element_selector_xpath}]', element_selector_api_name, element_selector_xpath)
    return target_ele

  def tap(self, button_api):
    # get the currently executing code
    code_lines = self.config.compiled_code_lines
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"Tap: {button_api} at line {lineno}, code is:{code_lines[lineno - 1]}, action count: {self.action_count}")
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = self.config.line_mappings[lineno - 1]
    original_code_line = self.config.code_lines[lineno_in_original_script]

    if isinstance(button_api, str):
      button_api_name = button_api.split('$')[-1]
      ele_data = {
          'xpath': self.api_xpaths[button_api_name],
          'api_name': button_api_name,
          'text': None,
          'action_type': 'touch',
      }

    else:
      button_api_name = button_api.api_name if button_api.api_name else button_api.element_list_xpath

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
    self.check_action_count()

  def long_tap(self, button_api):
    # get the currently executing code
    code_lines = self.config.compiled_code_lines
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(
        f"long tap: {button_api} at line {lineno}, code is:{code_lines[lineno - 1]}, action count: {self.action_count}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = self.config.line_mappings[lineno - 1]
    original_code_line = self.config.code_lines[lineno_in_original_script]

    if isinstance(button_api, str):
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
    self.check_action_count()

  def set_text(self, text_api, text):
    # get the currently executing code
    code_lines = self.config.compiled_code_lines
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(f"set_text: {text_api} at line {lineno}, code is:{code_lines[lineno - 1]}, action count: {self.action_count}")
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = self.config.line_mappings[lineno - 1]
    original_code_line = self.config.code_lines[lineno_in_original_script]

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

    self.execute_action(ele_data)
    self.check_action_count()

  def scroll(self, scroller_api, direction):
    # get the currently executing code
    code_lines = self.config.compiled_code_lines
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(f"scroll {direction}: {scroller_api} at line {lineno}, code is:{code_lines[lineno - 1]}, action count: {self.action_count}")
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = self.config.line_mappings[lineno - 1]
    original_code_line = self.config.code_lines[lineno_in_original_script]

    last_screen = self.last_screen
    
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
    self.check_last_screen_html()
    self.check_action_count()
    is_to_bottom = False if not last_screen else self.last_screen == last_screen
    return is_to_bottom

  def get_text(self, element_selector):
    '''
    return the text of the element as a string.
    '''

    # get the currently executing code
    code_lines = self.config.compiled_code_lines
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(f"get_text: {element_selector} at line {lineno}, code is:{code_lines[lineno - 1]}, action count: {self.action_count}")
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = self.config.line_mappings[lineno - 1]
    original_code_line = self.config.code_lines[lineno_in_original_script]

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
    
    target_ele = self.navigate_and_get_target_element(
        element_selector_api_name,
        element_selector_xpath,
        caller_type='get_text',
        statement={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        })
    
    self.check_action_count()
    # not change the status
    
    text = self.element_tree.get_text(target_ele)
    text = text.replace('--', ' ')
    return text

  def get_attributes(self, element_selector):
    '''
    return the attributes of the element as a dict, dict keys include "selected", "checked", "scrollable", dict values are boolean. eg. get_attributes($files[3])["selected"].
    '''

    # get the currently executing code
    code_lines = self.config.compiled_code_lines
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(f"get_attributes: {element_selector} at line {lineno}, code is:{code_lines[lineno - 1]}, action count: {self.action_count}")
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = self.config.line_mappings[lineno - 1]
    original_code_line = self.config.code_lines[lineno_in_original_script]

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
    
    target_ele = self.navigate_and_get_target_element(
        element_selector_api_name,
        element_selector_xpath,
        caller_type='get_attributes',
        statement={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        })
    
    self.check_action_count()
    # not change the screen
    
    target_ele_attrs = target_ele.get_attributes()
    target_ele_attrs['text'] = target_ele_attrs.replace('--', ' ')
    return target_ele_attrs

  def back(self):
    '''
    close the current window
    '''

    # get the currently executing code
    code_lines = self.config.compiled_code_lines
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    print(f"go back at line {lineno}, code is:{code_lines[lineno - 1]}, action count: {self.action_count}")
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = self.config.line_mappings[lineno - 1]
    original_code_line = self.config.code_lines[lineno_in_original_script]

    state = self.state
    element_tree = self.element_tree

    _save2log(
        save_path=self.save_path,
        log_file=self.config.log_file,
        element_tree=element_tree,
        idx=None,
        inputs=None,
        action_type='go back',
        api_name=None,
        xpath=None,
        currently_executing_code={
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        },
        screenshot=state.pixels.copy())

    self.env.execute_action(json_action.JSONAction(**{"action_type": "navigate_back"}))
    time.sleep(WAIT_AFTER_ACTION_SECONDS)
    self.update_state()
    self.check_last_screen_html()
    self.check_action_count()


class ElementList:

  def __init__(self, api_name, api_xpath, verifier: Verifier) -> None:
    # all element_lists can be uniquely identified by their api_xpath. If one api_name is provided, we can retrieve its xpath from api_xpaths. If api_name is not provided, such as a dynamic element at runtime, then its xpath must be provided.
    self.env = verifier.env
    self.save_path = verifier.save_path
    self.config = verifier.config
    self.doc = verifier.doc
    
    self.api_name = api_name
    self.api_xpaths = verifier.api_xpaths
    
    if self.api_name:
      self.check_api_name(api_name)
    if not api_xpath:
      self.element_list_xpath = self.api_xpaths[api_name]
    else:
      self.element_list_xpath = api_xpath
    self.verifier = verifier
    self.index = 0
    
    self.status = verifier.status
  
  @property
  def state(self):
    return self.verifier.state

  @property
  def element_tree(self):
    return self.verifier.element_tree
  
  @property
  def action_count(self):
    return self.status.action_count
  
  def check_action_count(self):
    self.status.check_action_count()
  
  def check_last_screen_html(self):
    return self.verifier.check_last_screen_html()
  
  def update_state(self):
    self.verifier.update_state()

  def check_api_name(self, api_name):
    if api_name not in self.api_xpaths.keys():  # not found xpath
      # find the first line with the api_name in the original script (combined with the preparation, this is to stay the same with tap, set_text, etc.)
      raise APIError(f'Invalid {api_name}', api_name)

  def convert_ele_attr_to_elementlist(self, ele_attr):
    ele_xpath = f"//{ele_attr.type_}[@id='{ele_attr.id}']"
    elementlist = ElementList(
        api_name=None,
        api_xpath=ele_xpath,
        verifier=self.verifier)
    return ele_xpath, elementlist

  def __getitem__(self, selector):
    # get the currently executing code
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, f'index[{selector}]', selector)
    
    element_selector_api_name = self.api_name if self.api_name else self.element_list_xpath
    element_selector_xpath = self.element_list_xpath
    statement = {
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        }
    
    target_ele_group = self.verifier.navigate_and_get_target_element(element_selector_api_name, element_selector_xpath, f'index[{selector}]', statement)
    
    # Default to integer index if not a custom selector
    if isinstance(selector, int):
      ele_attr = self.element_tree.get_children_by_idx(target_ele_group, selector)
      matched_xpath, matched_ele = self.convert_ele_attr_to_elementlist(
          ele_attr)
      
      return matched_ele
    
    self.check_action_count()
    # no change screen
    raise ActionError(f"Fail to __getitem__({selector}) in {self.api_name}[{self.element_list_xpath}]", self.api_name, self.element_list_xpath, '__getitem__', selector)

  def __iter__(self):
    '''
        in order to support iteration, we need to return an iterator object from __iter__() method.
        '''
    return self

  def __next__(self):
    '''
    return the next element in the current element's children to support iteration.
    '''
    # get the currently executing code
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, '__next__', self.api_name)
    
    element_selector_api_name = self.api_name if self.api_name else self.element_list_xpath
    element_selector_xpath = self.element_list_xpath
    statement = {
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        }
    
    target_ele_group= self.verifier.navigate_and_get_target_element(element_selector_api_name, element_selector_xpath, f'[{self.index}]next', statement)

    ele_list_children = self.element_tree.get_children_by_ele(target_ele_group)
    if not ele_list_children:
      raise StopIteration
    self.check_action_count()
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
    # get the currently executing code
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'match', match_data)

    element_selector_api_name = self.api_name if self.api_name else self.element_list_xpath
    element_selector_xpath = self.element_list_xpath
    statement = {
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        }
    
    target_ele = self.verifier.navigate_and_get_target_element(element_selector_api_name, element_selector_xpath, f'match[{match_data}]', statement)

    ele_list_children = self.element_tree.get_children_by_ele(target_ele)
    
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

    self.check_action_count()
    # todo:: how to deal with multiple matched elements
    if len(matched_elements) == 0:
      raise ActionError(f'Fail to match({match_data}) in {self.api_name}[{self.element_list_xpath}]', self.api_name, self.element_list_xpath, 'match', match_data)
    
    return matched_elements[0]

  def __len__(self):
    # get the currently executing code
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, '__len__', self.api_name)
    
    element_selector_api_name = self.api_name if self.api_name else self.element_list_xpath
    element_selector_xpath = self.element_list_xpath
    statement = {
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        }
    
    target_ele = self.verifier.navigate_and_get_target_element(element_selector_api_name, element_selector_xpath, '__len__', statement)

    if not target_ele: # todo:: maybe it's 0
      logging.warning(f'not found {self.api_name}[{self.element_list_xpath}]')
      return 0
    # ele_list_children = element_tree.get_children_by_ele(target_ele)
    ele_list_children = target_ele.children
    self.check_action_count()
    return len(ele_list_children)

  def get_current_code_line(self, lineno: int, action: str, element_selector_name: str):
    # get the currently executing code
    code_lines = self.config.compiled_code_lines
    print(
        f"{action}: {element_selector_name} at line {lineno}, code is:{code_lines[lineno - 1]}, action count: {self.action_count}"
    )
    current_code_line = code_lines[lineno - 1]
    lineno_in_original_script = self.config.line_mappings[lineno - 1]
    original_code_line = self.config.code_lines[lineno_in_original_script]

    return current_code_line, lineno_in_original_script, original_code_line

  def find_target_element_in_group(self, element_selector_api_name: str, element_selector_xpath: str, caller_type: str, statement: dict):
    
    target_ele = None
    element_tree = self.element_tree
    target_ele_group = self.verifier.navigate_and_get_target_element(self.api_name, self.element_list_xpath, caller_type, statement)
    subtree = element_tree.extract_subtree(target_ele_group.id)
    if subtree:
      target_ele = subtree.get_ele_by_xpath(element_selector_xpath)

    if not target_ele:
      if self.doc.check_api_name_in_current_screen(element_selector_api_name, self.element_tree.skeleton):
        raise XPathError(f'Not Exist {element_selector_api_name}[{element_selector_xpath}]', element_selector_api_name, element_selector_xpath)
      else:
        raise NotFoundError(f'Not Found {element_selector_api_name}[{element_selector_xpath}] in {self.api_name}[{self.element_list_xpath}]', element_selector_api_name, element_selector_xpath, self.api_name, self.element_list_xpath)
    
    return target_ele
    
  def tap(self, button_api):
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    
    if isinstance(button_api, str):
      button_api_name = button_api.split('$')[-1]
      button_api_xpath = self.api_xpaths[button_api_name]
    elif isinstance(button_api, ElementList):
      button_api_name = button_api.api_name if button_api.api_name else button_api.element_list_xpath
      button_api_xpath = button_api.element_list_xpath
    else:
      raise APIError(f'Invalid {button_api}', button_api)

    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'touch', button_api_name)
    statement = {
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        }
    
    target_ele = self.find_target_element_in_group(button_api_name, button_api_xpath, 'touch', statement)

    converted_action = agent_utils.convert_action("touch", target_ele, "")
    if converted_action['action_type'] == 'wait':
      raise ActionError(f'Fail to tap({button_api_name}) in {self.api_name}[{self.element_list_xpath}]', self.api_name, self.element_list_xpath, 'touch', button_api_name)
    
    self.env.execute_action(json_action.JSONAction(**converted_action))
    time.sleep(WAIT_AFTER_ACTION_SECONDS)
    self.update_state()
    self.check_last_screen_html()
    
    self.check_action_count()

  def long_tap(self, button_api):
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    
    if isinstance(button_api, str):
      button_api_name = button_api.split('$')[-1]
      button_api_xpath = self.api_xpaths[button_api_name]
    elif isinstance(button_api, ElementList):
      button_api_name = button_api.api_name if button_api.api_name else button_api.element_list_xpath
      button_api_xpath = button_api.element_list_xpath
    else:
      raise APIError(f'Invalid {button_api}', button_api)
    
    
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'long_touch', button_api_name)
    statement = {
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        }
    
    target_ele = self.find_target_element_in_group(button_api_name, button_api_xpath, 'long_touch', statement)

    converted_action = agent_utils.convert_action("long_touch", target_ele, "")
    if converted_action['action_type'] == 'wait':
      raise ActionError(f'Fail to long_tap({button_api_name}) in {self.api_name}[{self.element_list_xpath}]', self.api_name, self.element_list_xpath, 'long_touch', button_api_name)
    
    self.env.execute_action(json_action.JSONAction(**converted_action))
    time.sleep(WAIT_AFTER_ACTION_SECONDS)
    self.update_state()
    self.check_last_screen_html()
    
    self.check_action_count()

  def set_text(self, input_api, text):
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    
    if isinstance(input_api, str):
      input_api_name = input_api.split('$')[-1]
      input_api_xpath = self.api_xpaths[input_api_name] # todo:: if multiple, we can try step by step
    elif isinstance(input_api, ElementList):
      input_api_name = input_api.api_name if input_api.api_name else input_api.element_list_xpath
      input_api_xpath = input_api.element_list_xpath
    else:
      raise APIError(f'Invalid {input_api}', input_api)
    
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'set_text', input_api_name)
    statement = {
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        }
    
    target_ele = self.find_target_element_in_group(input_api_name, input_api_xpath, 'set_text', statement)

    converted_action = agent_utils.convert_action("set_text", target_ele, text)
    if converted_action['action_type'] == 'wait':
      raise ActionError(f'Fail to set_text({input_api}) in {self.api_name}[{self.element_list_xpath}]', self.api_name, self.element_list_xpath, 'set_text', input_api)
    
    self.env.execute_action(json_action.JSONAction(**converted_action))
    time.sleep(WAIT_AFTER_ACTION_SECONDS)
    self.update_state()
    self.check_last_screen_html()
    
    self.check_action_count()

  def get_text(self, element_selector):
    '''
    return the text of the element as a string.
    '''
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    
    if isinstance(element_selector, str):
      element_selector = element_selector.split('$')[-1]
      element_selector_xpath = self.api_xpaths[element_selector]
      element_selector_api_name = element_selector
    elif isinstance(element_selector, ElementList):
      element_selector_xpath = element_selector.element_list_xpath
      element_selector_api_name = element_selector.api_name if element_selector.api_name else element_selector.element_list_xpath
    else:
      raise APIError(f'Invalid {element_selector}', element_selector)
    
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'get_text', element_selector_api_name)
    statement = {
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        }
    
    target_ele = self.find_target_element_in_group(element_selector_api_name, element_selector_xpath, 'get_text', statement)
    
    self.check_action_count()
    # not change screen
    
    text = target_ele.text if target_ele.text else ''
    text = text.replace('--', ' ')
    return text

  def get_attributes(self, element_selector):
    '''
    return the attributes of the element as a dict, dict keys include "selected", "checked", "scrollable", dict values are boolean. eg. get_attributes($files[3])["selected"].
    '''
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    lineno = caller_frame.f_lineno
    
    if isinstance(element_selector, str):
      element_selector = element_selector.split('$')[-1]
      element_selector_xpath = self.api_xpaths[element_selector]
      element_selector_api_name = element_selector
    elif isinstance(element_selector, ElementList):
      element_selector_xpath = element_selector.element_list_xpath
      element_selector_api_name = element_selector.api_name if element_selector.api_name else element_selector.element_list_xpath
    else:
      raise APIError(f'Invalid {element_selector}', element_selector)
    
    current_code_line, lineno_in_original_script, original_code_line = self.get_current_code_line(lineno, 'get_attributes', element_selector_api_name)
    statement = {
            'current_code': current_code_line,
            'original_lineno': lineno_in_original_script,
            'original_code': original_code_line
        }
    
    target_ele = self.find_target_element_in_group(element_selector_api_name, element_selector_xpath, 'get_attributes', statement)
    
    self.check_action_count()
    # not change screen
    target_ele_attrs = target_ele.get_attributes()
    target_ele_attrs['text'] = target_ele_attrs.replace('--', ' ')
    return target_ele_attrs
  
  def scroll(self, scroller_api, direction):
    return self.verifier.scroll(scroller_api, direction)

  def back(self):
    self.verifier.back()
