# Copyright 2024 The android_world Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Agent for human playing."""

import datetime
import sys
import time

from android_world.agents import base_agent
from android_world.agents import agent_utils
from android_world.env import interface
from android_world.env import json_action

from android_world.agents.agent_utils import ElementTree


class HumanAgent(base_agent.EnvironmentInteractingAgent):
  """Human agent; wait for user to indicate they are done."""

  # Wait a few seconds for the screen to stabilize after executing an action.
  WAIT_AFTER_ACTION_SECONDS = 2.0

  def __init__(self,
               env: interface.AsyncEnv,
               save_path: str,
               name: str = 'HumanAgent'):

    super().__init__(env, name)
    self.save_path = save_path

  def step(self, goal: str) -> base_agent.AgentInteractionResult:
    state = self.get_post_transition_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)

    marked_ids = self.mark_dynamic_ids(element_tree)
    
    action_list = [
        "wait", "click", "input_text", "scroll", "long_press", "navigate_home",
        "navigate_back", "open_app", "answer", "keyboard_enter", "status"
    ]
    print('\033[0;32m', 'goal: ', goal, '\033[0m')
    print('\033[0;32m', '-' * 40, 'Actions', '-' * 40, '\033[0m')
    print('\n'.join(
        [f'{index}: {action}' for index, action in enumerate(action_list)]))
    response = input('Please input the action id (or q to quit):')
    if response == 'q':
      sys.exit()
    try:
      response = int(response)
    except:
      print('\033[1;31m' + 'Invalid id, replaced by wait action.' + '\033[0m')
      response = 0

    action_type = action_list[response]
    print(f'Action: {action_type}')

    action_details, ele_id = self.get_action_and_id(action_type, element_tree)

    if action_details['action_type'] == 'answer':
      print('Agent answered with: ' + action_details['text'])

    done = False
    if action_details['action_type'] == 'status':
      done = True
    else:
      self.env.execute_action(json_action.JSONAction(**action_details))

    time.sleep(self.WAIT_AFTER_ACTION_SECONDS)

    result = {}
    result['elements'] = state.ui_elements

    timestamp = datetime.datetime.now().strftime('%Y-%m-%d_T%H%M%S')

    if action_details['action_type'] != "wait" and len(marked_ids) != 0:
      agent_utils.save_to_yaml(self.save_path, element_tree.str, timestamp,
                               action_details['action_type'], action_details, ele_id,
                               action_details.get('text', None),
                               self.env.device_screen_size[0],
                               self.env.device_screen_size[1], marked_ids)

      agent_utils.save_screenshot(self.save_path, timestamp,
                                  state.pixels.copy())

      agent_utils.save_raw_state(self.save_path, timestamp, state.forest)

    return base_agent.AgentInteractionResult(done, result)

  def get_post_transition_state(self) -> interface.State:
    return self.env.get_state()

  def get_action_and_id(self, action_type: str,
                        element_tree: ElementTree) -> tuple[dict, int | None]:
    action_details = {'action_type': action_type}
    wait_action = {'action_type': 'wait'}

    if action_type == "status":
      goal_status = ['complete', 'infeasible']
      status_id = input(f'Please input the status id in {goal_status}.')
      try:
        status = goal_status[int(status_id)]
        action_details['goal_status'] = status
      except:
        print('\033[1;31m' + 'Invalid id, replaced by wait action.' + '\033[0m')
        return wait_action, None

    elif action_type == "answer":
      action_details['text'] = input('Please input the text:')

    elif action_type in ["click", "long_press", "input_text", "scroll"]:
      print('\033[0;32m', '-' * 40, 'State', '-' * 40, '\033[0m')
      print(element_tree.get_str(is_color=True))
      ele_id = input(f'Please input the element id with {action_type}:')
      try:
        ele_id = int(ele_id)
        ele = element_tree.ele_map[ele_id]
      except:
        print('\033[1;31m' + 'Invalid id, replaced by wait action.' + '\033[0m')
        return wait_action, None

      if ele.local_id is None:
        print(
            '\033[1;31m' +
            f'Element: {ele_id} is NOT interacted with, replaced by wait action.'
            + '\033[0m')
        return wait_action, None

      if ele.check_action(action_type) is False:
        print('\033[1;31m' + 'Invalid action, replaced by wait action.' +
              '\033[0m')
        return wait_action, None

      if action_type in ["click", "long_press", "input_text"]:
        x, y = ele.ele.bbox_pixels.center
        x, y = int(x), int(y)
        action_details['x'] = x
        action_details['y'] = y
        if action_type == "input_text":
          action_details['text'] = input('Please input the text:')
      elif action_type == "scroll":
        action_details['index'] = ele.local_id
        direction_list = ['up', 'down', 'left', 'right']
        direction = input(f'Please input the direction id in {direction_list}:')
        try:
          direction = direction_list[int(direction)]
          action_details['direction'] = direction
        except:
          print('\033[1;31m' + 'Invalid id, replaced by wait action.' +
                '\033[0m')
          return wait_action, None

      return action_details, ele_id

    elif action_type == "open_app":
      app_name = input(
          'Please input the app name\n(nothing will happen if the app is not installed):\n'
      )
      action_details['app_name'] = app_name

    return action_details, None

  def mark_dynamic_ids(self, element_tree: ElementTree) -> list[int]:
    dynamic_ids = set()
    print('\033[0;32m', '-' * 40, 'Dynamic', '-' * 40, '\033[0m')
    print(element_tree.get_str(is_color=True))
    ids = input('Please input the dynamic ids, like `0 2-5 8`:')
    ids = ids.split()
    for id in ids:
      if '-' in id:
        start, end = id.split('-')
        start, end = int(start), int(end)
        for i in range(start, end + 1):
          if i < 0 or i >= element_tree.size:
            break
          dynamic_ids.add(i)
      else:
        i = int(id)
        if i < 0 or i >= element_tree.size:
          continue
        dynamic_ids.add(int(id))

    return list(dynamic_ids)
