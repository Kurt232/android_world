"""Agent for executing code script."""

import datetime
import sys
import time
import os
import re
import traceback

from lxml import etree

from android_world.agents import base_agent
from android_world.agents import agent_utils
from android_world.agents import infer
from android_world.env import interface
from android_world.env import json_action

from android_world.agents.agent_utils import ElementTree

from android_world.script_utils.ui_apis import Verifier, regenerate_script
from android_world.script_utils import tools
from android_world.script_utils.bug_processor import BugProcessorv2
from android_world.script_utils.solution_generator import SolutionGenerator


def process_error_info(original_script, compiled_script, traceback, error,
                       line_mappings):
  print(f"Exception caught: {error}")
  print("Traceback details:")
  print(traceback)

  # extract the line number of the error
  tb_lines = traceback.split('\n')

  for line in tb_lines:
    if 'File "<string>"' in line:
      print(line.strip())
      match = re.search(r'line (\d+)', line)
      if match:  # localized the error line number
        try:
          line_number = match.group(1)
          print(f'The line number is: {line_number}')
          error_line_number_in_compiled_script = int(
              line_number
          ) - 1  # the line number of the error info often starts from 1, but in the mappings, it starts from 0
          error_line_number_in_original_script = line_mappings[
              error_line_number_in_compiled_script]
          error_line_in_compiled_script = compiled_script.split(
              '\n')[error_line_number_in_compiled_script]
          error_line_in_original_script = original_script.split(
              '\n')[error_line_number_in_original_script]
        except:
          print(f'Error in extracting the line number: {line_number}')
          error_line_number_in_compiled_script = None
          error_line_number_in_original_script = None
          error_line_in_compiled_script = None
          error_line_in_original_script = None
      else:
        print('No line number found')
        error_line_in_compiled_script = line
        error_line_in_original_script, error_line_number_in_compiled_script, error_line_number_in_original_script = None, None, None

  return {
      'original_script':
          original_script,
      'compiled_script':
          compiled_script,
      'traceback':
          traceback,
      'error':
          error,
      'error_line_number_in_compiled_script':
          error_line_number_in_compiled_script,
      'error_line_number_in_original_script':
          error_line_number_in_original_script,
      'error_line_in_compiled_script':
          error_line_in_compiled_script,
      'error_line_in_original_script':
          error_line_in_original_script
  }


def format_apis(env: interface.AsyncEnv, api_xpaths):

  def _recursively_get_ele_property(ele_tree: ElementTree, ele):
    ele_text = ele_tree.get_ele_text(ele)
    ele_content_desc = ele_tree.get_content_desc(ele)
    return {'text': ele_text, 'content_desc': ele_content_desc}

  def _get_ordered_ui_apis(ele_tree: ElementTree, ui_state_desc, api_xpaths):
    ui_apis = {}
    for api_name, api_xpath in api_xpaths.items():
      root = etree.fromstring(ui_state_desc)
      eles = root.xpath(api_xpath)
      if not eles:
        continue
      ele_desc = etree.tostring(eles[0], pretty_print=True).decode(
          'utf-8')  # only for father node
      id_str = re.search(r' id="(\d+)"', ele_desc).group(1)
      id = int(id_str)

      ele = ele_tree.get_ele_by_xpath(api_xpath)
      ele_children = ele_tree.get_children_by_ele(ele)
      # ele_properties = ele.dict(only_original_attributes=True)

      api_desc = {
          'name':
              api_name,
          'property':
              _recursively_get_ele_property(ele_tree, ele),
          'children': [
              _recursively_get_ele_property(ele_tree, child)
              for child in ele_children
          ]
      }

      ui_apis[id] = api_desc

    # iterate over ui_apis to get the order of apis
    ui_apis_ordered = []
    for id in sorted(ui_apis.keys()):
      ui_apis_ordered.append(ui_apis[id])
    # import pdb
    # pdb.set_trace()
    return ui_apis_ordered

  current_state = env.get_state()
  element_tree = agent_utils.forest_to_element_tree(current_state.forest)

  state_desc = element_tree.get_str(is_color=False)
  ui_apis_ordered = _get_ordered_ui_apis(element_tree, state_desc, api_xpaths)
  ui_apis_str = ''
  for ui_api in ui_apis_ordered:
    ui_apis_str += f'\nelement: {ui_api["name"]}\n'
    if ui_api['property']['text']:
      ui_apis_str += f'\tText: {ui_api["property"]["text"]}\n'
    if ui_api['property']['content_desc']:
      ui_apis_str += f'\tContent Description: {ui_api["property"]["content_desc"]}\n'
    if ui_api['children'] != []:
      ui_apis_str += '\tChildren:\n'
      for child in ui_api['children']:
        if child['text']:
          ui_apis_str += f'\t\tChild text: {child["text"]};'
        if child['content_desc']:
          ui_apis_str += f'\t\tChild content description: {child["content_desc"]}\n'
  return ui_apis_str


class CodeAgent(base_agent.EnvironmentInteractingAgent):
  """code agent"""

  # Wait a few seconds for the screen to stabilize after executing an action.
  WAIT_AFTER_ACTION_SECONDS = 2.0
  MAX_RETRY_TIMES = 3

  # QUERY_FIRSTTIME = True

  def __init__(self,
               env: interface.AsyncEnv,
               llm: infer.LlmWrapper,
               save_path: str,
               name: str = 'CodeAgent'):

    super().__init__(env, name)
    self.llm = llm  # todo::
    self.save_path = save_path

  def step(self, goal: str) -> base_agent.AgentInteractionResult:
    tools.write_txt_file('tmp/task.txt', goal)
    """
    only execute once for code script
    """
    # todo:: add a config
    app_name = tools.load_txt_file('tmp/app_name.txt')
    for retry_time in range(self.MAX_RETRY_TIMES):
      api_xpaths = tools.load_json_file('tmp/api_xpaths_checked.json')
      api_data = tools.load_json_file('tmp/apis/notes.json')
      if retry_time == 0:
        # restart the app first in case the script couldn't run and the app has not been start
        self.env.execute_action(
            json_action.JSONAction(**{
                'action_type': 'open_app',
                'app_name': app_name
            }))
        time.sleep(self.WAIT_AFTER_ACTION_SECONDS)

        # if there is no solution code yet at the first time, we need to generate one
        task = tools.load_txt_file('tmp/task.txt')
        solution_generator = SolutionGenerator('tmp/apis/notes.json', self.llm)
        formatted_apis = format_apis(self.env, api_xpaths)
        solution_code = solution_generator.get_solution(
            app_name=app_name,
            prompt_answer_path=os.path.join(self.save_path, f'solution.json'),
            task=task,
            ui_elements=formatted_apis,
            enable_dependency=False,
            model_name='gpt-4o')
        tools.write_txt_file('tmp/code.txt', solution_code)

      code = tools.load_txt_file('tmp/code.txt')
      code = tools.get_combined_code('data/notes_preparation.txt', code)
      tools.write_txt_file('tmp/combined_code.txt', code)
      dependencies = tools.load_json_file('tmp/api_paths.json')
      verifier = Verifier(self, self.env, self.save_path, api_xpaths, api_data,
                          dependencies)
      code_script, line_mappings = regenerate_script(self.code, 'verifier',
                                                     'self.device',
                                                     'code_policy',
                                                     'api_xpaths')
      tools.write_txt_file('tmp/compiled_code.txt', code_script)
      tools.dump_json_file('tmp/line_mappings.json', line_mappings)
      # in case some silly scripts include no UI actions at all, we make an empty log for batch_verifying
      log_path = os.path.join(self.save_path, f'log.yaml')
      tools.dump_yaml_file(log_path, {'records': [], 'step_num': 0})
      try:
        exec(code_script)
      except Exception as e:
        # save_current_ui_to_log(code_policy, api_name=None)
        tb_str = traceback.format_exc()
        error_path = os.path.join(self.save_path, f'error.json')
        error_info = process_error_info(code, code_script, tb_str, str(e),
                                        line_mappings)

        tools.dump_json_file(error_path, error_info)

        bug_processor = BugProcessorv2(
            app_name=app_name,
            log_path=log_path,
            error_log_path=error_path,
            task=tools.load_txt_file('tmp/task.txt'),
            raw_solution=tools.load_txt_file('tmp/code.txt'),
            apis_path='tmp/apis/notes.json',
            api_xpath_file='tmp/api_xpaths_checked.json')

        stuck_apis_str = format_apis(self.env, api_xpaths)
        script = bug_processor.process_bug(prompt_answer_path=os.path.join(
            self.save_path, f'debug_task{self.task_id}_turn{retry_time}.json'),
                                           enable_dependency=False,
                                           model_name='gpt-4o',
                                           stuck_ui_apis=stuck_apis_str)
        tools.write_txt_file('tmp/code.txt', script)

    result = {}

    if retry_time == self.MAX_RETRY_TIMES - 1:
      result['result'] = 'failed'
    else:
      result['result'] = 'succeed'

    return base_agent.AgentInteractionResult(True, result)

  def get_post_transition_state(self) -> interface.State:
    return self.env.get_state()
