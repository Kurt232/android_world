"""Agent for executing code script."""

import time
import os
import re
import traceback

from absl import logging

from android_world.agents import base_agent
from android_world.env import interface
from android_world.env import json_action

from android_world.agents.agent_utils import ElementTree

from android_world.script_utils.ui_apis import CodeConfig, CodeStatus, Verifier, ElementList, regenerate_script, _save2log
from android_world.script_utils import tools
from android_world.script_utils.bug_processor import BugProcessorV3
from android_world.script_utils.solution_generator import SolutionGenerator
from android_world.script_utils.api_doc import ApiDoc
from android_world.script_utils.err import XPathError, APIError, ActionError, NotFoundError


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


class CodeAgent(base_agent.EnvironmentInteractingAgent):
  """code agent"""

  # Wait a few seconds for the screen to stabilize after executing an action.
  WAIT_AFTER_ACTION_SECONDS = 2.0
  MAX_RETRY_TIMES = 3

  FREEZED_CODE = False
  
  APP_LIST = ['broccoli', 'pro expense', 'clock', 'Simple SMS Messenger']
  def __init__(self,
               env: interface.AsyncEnv,
               task_names: str,
               app_name: str,
               doc_name: str,
               save_path: str,
               name: str = 'CodeAgent'):

    super().__init__(env, name)
    app_name = app_name.strip()
    if app_name not in self.APP_LIST:
      raise ValueError(f'Unknown app name: {app_name} in\n\t{self.APP_LIST}')
    
    doc_path = f'tmp/xdocs_0820/{doc_name}.json'
    if not os.path.exists(doc_path):
      raise ValueError(f'Unknown doc name: {doc_name}')

    self.app_name = app_name
    self.task_names = task_names
    self.doc = ApiDoc(doc_path)
    self.save_dir = save_path
    
    self.goal_set = set()
    self.save_path = None
  
  def __del__(self):
    self.doc.save()
  
  @property
  def task_name(self):
    return self.task_names[len(self.goal_set) - 1]

  def step(self, goal: str) -> base_agent.AgentInteractionResult:
    """
    only execute once for code script
    """
    self.goal_set.add(goal)
    task = goal
    app_name = self.app_name
    self.save_path = os.path.join(self.save_dir, self.task_name)
    code_status = CodeStatus()
    if not os.path.exists(self.save_path):
      os.makedirs(self.save_path)
    
    logging.info(f'Executing task: {task}')
    tools.write_txt_file(f'{self.save_path}/task.txt', task)
    app_doc = self.doc
    
    err = None
    done = False
    for retry_time in range(self.MAX_RETRY_TIMES):
      if retry_time == 0:
        # restart the app first in case the script couldn't run and the app has not been start
        self.env.execute_action(
            json_action.JSONAction(**{
                'action_type': 'open_app',
                'app_name': app_name
            }))
        time.sleep(self.WAIT_AFTER_ACTION_SECONDS)
        
      if retry_time == 0: # first time
        # generate code
        if self.FREEZED_CODE:
          code = tools.load_txt_file(f'tmp/code.txt')
        else:
          solution_generator = SolutionGenerator(app_name, task, app_doc)
          solution_code = solution_generator.get_solution(
              prompt_answer_path=os.path.join(self.save_path, f'solution.json'),
              env=self.env,
              model_name='gpt-4o')
          code = solution_code
      else: # retry
        bug_processor = BugProcessorV3(
            app_name=app_name,
            task=task,
            doc=app_doc,
            error_info=error_info,
            code=code,
            err = err)
        
        # update the save_path for retry
        self.save_path = os.path.join(self.save_dir, self.task_name, f'{retry_time}')
        os.makedirs(self.save_path, exist_ok=True)
        
        if isinstance(err, XPathError):
          bug_processor.fix_invalid_xpath(
            env=env, 
            api_name=err.name, 
            prompt_answer_path=os.path.join(self.save_path, f'fix_xpath.json'), 
            model_name='gpt-4o')
        
        code = bug_processor.get_fixed_solution(# re-generate code
            prompt_answer_path=os.path.join(self.save_path, f'solution.json'),
            env=env,
            model_name='gpt-4o')
      
      tools.write_txt_file(f'{self.save_path}/code.txt', code)
      
      code_script, line_mappings = regenerate_script(code, 'verifier')
      tools.write_txt_file(f'{self.save_path}/compiled_code.txt', code_script)
      tools.dump_json_file(f'{self.save_path}/line_mappings.json', line_mappings)
      
      # in case some silly scripts include no UI actions at all, we make an empty log for batch_verifying
      tools.dump_yaml_file(os.path.join(self.save_path, f'log.yaml'), {'records': [], 'step_num': 0})
      
      env = self.env
      config = CodeConfig(app_name, app_doc, self.save_path, code, code_script, line_mappings)
      code_status.reset()
      
      t1 = time.time()
      
      # execution
      verifier = Verifier(env, config, code_status)
      
      try:
        exec(code_script)
        done = True
      except Exception as e:
        tb_str = traceback.format_exc()
        error_info = process_error_info(code, code_script, tb_str, str(e),
                                        line_mappings)

        error_path = os.path.join(self.save_path, f'error.json')
        tools.dump_json_file(error_path, error_info)
        err = e
      
      _save2log(
          save_path=self.save_path,
          log_file='log.yaml',
          element_tree=verifier.element_tree,
          idx=None,
          inputs=None,
          action_type=None,
          api_name=None,
          xpath=None,
          currently_executing_code=None,
          comment='done',
          screenshot=verifier.state.pixels.copy())
      t2 = time.time()
      runtime = t2 - t1
      tools.write_txt_file(f'{self.save_path}/runtime.txt', "%f" % runtime)
      if done:
        break
    
    result = {'result': 'succeed' if done else 'failed'}

    return base_agent.AgentInteractionResult(True, result)

  def get_post_transition_state(self) -> interface.State:
    return self.env.get_state()
