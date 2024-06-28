"""Agent for droidbot."""
import time
import re

from android_world.agents import base_agent
from android_world.agents import infer
from android_world.env import interface
from android_world.env import json_action

from android_world.agents import droidbot_utils
from android_world.agents.droidbot_utils import ElementTree, EleAttr, Utils


class DroidbotAgent(base_agent.EnvironmentInteractingAgent):
  """DroidbotAgent"""

  def __init__(self,
               env: interface.AsyncEnv,
               llm: infer.Gpt4Wrapper,
               app_name: str,
               name: str = 'droidbot',
               ):
    """Initializes a DroidbotAgent.

    Args:
      env: The environment.
      llm: The text only LLM.
      name: The agent name.
    """
    super().__init__(env, name)
    self.llm = llm
    self.app_name = app_name
    
    self.history = []
    self.former_steps = [f'Start the {self.app_name} app.']

  def reset(self, go_home_on_reset: bool = False):
    super().reset(go_home_on_reset)
    self.env.hide_automation_ui()
    
    self.history = []
    self.former_steps = [f'Start the {self.app_name} app.']

  def start_app(self) -> base_agent.AgentInteractionResult:
    step_data = {
        'before_screenshot': None,
        'after_screenshot': None,
        'before_element_list': None,
        'after_element_list': None,
        'action_prompt': None,
        'action_output': None,
        'action_raw_response': None,
        'summary_prompt': None,
        'summary': None,
        'summary_raw_response': None,
    }
    
    state = self.get_post_transition_state()
    step_data['before_screenshot'] = state.pixels.copy()
    step_data['before_element_list'] = state.ui_elements
    
    self.env.execute_action(json_action.JSONAction(**{'action_type': 'open_app', 'app_name': self.app_name}))
    step_data['summary'] = f'Start the {self.app_name} app.'
    self.history.append(step_data)
    
    state = self.env.get_state()
    step_data['after_screenshot'] = state.pixels.copy()
    step_data['after_element_list'] = state.ui_elements

    self.history.append(step_data)
    
    return base_agent.AgentInteractionResult(
        False,
        step_data,
    ) 

  def step(self, goal: str) -> base_agent.AgentInteractionResult:
    if len(self.history) == 0:
      return self.start_app()
    
    # it could be defined by ourselves
    step_data = {
        'before_screenshot': None,
        'after_screenshot': None,
        'before_element_list': None,
        'after_element_list': None,
        'action_prompt': None,
        'action_output': None,
        'action_raw_response': None,
        'summary_prompt': None,
        'summary': None,
        'summary_raw_response': None,
    }
    print('----------step ' + str(len(self.history) + 1))

    
    # 1. acquiring the state description, using HTML
    state = self.get_post_transition_state()
    element_tree = droidbot_utils.forest_to_element_tree(state.forest)
    # print(element_tree.str)

    # Only save the screenshot for result visualization.
    step_data['before_screenshot'] = state.pixels.copy()
    step_data['before_element_list'] = state.ui_elements
    # 2. generate prompt
    action_prompt = self.get_prompt(element_tree.str, self.former_steps, goal)
    step_data['action_prompt'] = action_prompt
    # 3. get the action from the LLM
    action_output, raw_response = self.llm.predict(action_prompt)
    # action_output =   {
    #     "Steps": "Start the Contacts app, touch Alice in the main screen",
    #     "UI function": "The current UI displays the details of the contact Alice, including her contact information and options to interact with her, such as sending an email, calling, or sending an SMS.",
    #     "Analyses": "The task is to send an email to the contact Alice. The previous steps have already navigated to the contact details screen for Alice. The current UI provides a 'Send email' button, which can be used to accomplish the task.",
    #     "Finished": "No",
    #     "action_description": "Click the 'Send email' button to open the email composition interface and send an email to Alice.",
    #     "id": "596,671,728,803",
    #     "action_type": "touch",
    #     "input_text": "N/A"
    # }

    if not raw_response:
      raise RuntimeError('Error calling LLM in action selection phase.')

    step_data['action_output'] = action_output
    step_data['action_raw_response'] = raw_response
    # 4. parse the action output
    action, summary = self.parse_action_output(action_output)
    # If the output is not in the right format, add it to step summary which
    # will be passed to next step and return.
    if not action:
      print('Action prompt output is not in the correct format.')
      step_data['summary'] = (
          'Output for action selection is not in the correct format, so no'
          ' action is performed.')
      self.history.append(step_data)

      return base_agent.AgentInteractionResult(
          False,
          step_data,
      )

    if not summary:
      summary = 'Fail to summery the UI state.'
    step_data['summary'] = summary

    print('Action: ' + action)
    print('Summary: ' + summary)

    try:
      converted_action = json_action.JSONAction(**action)
    except Exception as e:  # pylint: disable=broad-exception-caught
      print('Failed to convert the output to a valid action.')
      print(str(e))
      step_data['summary'] = (
          'Can not parse the output to a valid action. Please make sure to pick'
          ' the action from the list with the correct json format!')
      self.history.append(step_data)

      return base_agent.AgentInteractionResult(
          False,
          step_data,
      )

    # 5. execute the action
    try:
      self.env.execute_action(converted_action)
    except Exception as e:  # pylint: disable=broad-exception-caught
      print(
          'Some error happened executing the action ',
          converted_action.action_type,
      )
      print(str(e))
      step_data['summary'] = ('Some error happened executing the action ' +
                              converted_action.action_type)
      self.history.append(step_data)

      return base_agent.AgentInteractionResult(
          False,
          step_data,
      )

    time.sleep(self.WAIT_AFTER_ACTION_SECONDS)
    # 6. get the post-transition state

    # Save screenshot only for result visualization.
    state = self.env.get_state()
    step_data['after_screenshot'] = state.pixels.copy()
    step_data['after_element_list'] = state.ui_elements

    self.history.append(step_data)

    return base_agent.AgentInteractionResult(
        False,
        step_data,
    )

  def reset(self, go_home_on_reset: bool = False):
    super().reset(go_home_on_reset)
    self.env.hide_automation_ui()
    self.history = []

  def get_post_transition_state(self) -> interface.State:
    return self.env.get_state()

  def get_prompt(self, state_desc, former_steps, task_desc):
    prefix = f"You are a personal assistant to operate a smartphone. You have a specific task to complete in this app. Consider the steps you've already taken in the app, the high-level plan to complete this task, and the current user interface (UI), described in simplified HTML. Your objective is to devise a UI action to be executed on this UI to accomplish your task, focusing only on future action to be taken in the current UI  and not including past ones. \n\n"
    task_desc = f"Task: {task_desc}\n\n"
    former_step_str = "Former steps: \n"
    for step_id, step in enumerate(former_steps):
      if step_id > 0:
        former_step_str += f"\tUI {step_id}: {step['UI']}\n\tAction: {step['action']}\n\n"
      else:
        former_step_str += f"\t{step}\n\n"

    current_ui_desc = f"Current UI: \n{state_desc}\n\n"
    # request_prompt = '''You should think step by step: First you should think about which actions are usually needed to complete the task based on your knowledge and with the hints (only if you think they are helpful). Then, you should think about the relations between the task, and relations between the previous UI actions and current UI state. After that, you should give the action. \n\nYour answer should always use the following format: { \"Steps\": \"...<steps usually involved to complete the above task on a smartphone>\", \"UI function\": \"<the function of the current UI>\", \"Analyses\": \"...<Analyses of the relations between the task, and relations between the previous UI actions and current UI state>\", \"Finished\": \"Yes/No\", \"Next step\": \"None or a <high level description of the next step>\", \"id\": \"an integer or -1 (if the task has been completed by previous UI actions)\", \"action\": \"touch, long_touch, scroll up/down, select, or input\", \"input_text\": \"N/A or ...<input text>\" } \n\n**Note that the id is the id number of the UI element to interact with. If you think the task has been completed by previous UI actions, the id should be -1. If 'Finished' is 'Yes', then the 'description' of 'Next step' is 'None', otherwise it is a high level description of the next step. If the 'action' is 'touch, long_touch, scroll, select, or input', the 'input_text' is N/A, otherwise it is the '<input text>'. Please do not output any content other than the JSON format. **'''
    request_prompt = '''Your answer should always use the following format: { \"Steps\": \"...<steps usually involved to complete the above task on a smartphone based on the hints and your knowledge>\", \"UI function\": \"<summarize the high level function of the this current UI>\", \"Analyses\": \"...<Analyses of the relations between the task, and relations between the previous UI actions and current UI state>\", \"Finished\": \"Yes/No(whether the task has been completed)\", \"action_description\": \"<a high level description of the UI action to be executed in the current UI>\", \"id\": \"the id of the target UI element of the action\", \"action_type\": \"touch, long_touch, scroll up/down, select or input\", \"input_text\": \"...<input text>\"} \nNote that you should follow the high-level plan about completing this task, and if the 'action_type' is 'input' or the target UI element is <input>, the 'input_text' is <the text you want to input to this UI element>, otherwise it is the N/A.\n**Please do not perform action to the non-interactive UI element that start with <p>. Please do not output any content other than the JSON format. **'''
    return f'{prefix}{current_ui_desc}{former_step_str}{request_prompt}'
    # end = "Your goal is to generate a plan in JSON format, detailing the UI actions needed to complete the task and explaining the rationale behind each action. The JSON should strictly follow this format: {'plan': '...<explanation of the plan>', 'actions': ['...<action 1>', '...<action 2>',..., '...<action n>']}, where actions include 'Touch: [button/checkbox]', 'Long_touch: [button]', 'scroll up', 'scroll down', and 'Touch: [input box] Input_text: [text to input]'(the last action combines a touch and text input in one step). **Please do not output any content other than the JSON format. Don't mention elements that only appear in HTML such as p. DON'T include previous actions. **"

  def parse_action_output(self, answer: str, element_map: dict[int, EleAttr]):

    def llm_action_extract(answer_dict):
      finished = False
      if 'yes' in answer_dict['Finished'].lower():
        finished = True

      pattern = r'\b(\d+),(\d+),(\d+),(\d+)\b'

      match = re.search(pattern, answer_dict['id'])
      if match:
        id = match.group(0)
      else:
        try:
          id = Utils.get_int_from_str(answer_dict['id'])
        except:
          id = -1
      raw_action_type = answer_dict['action_type']
      if raw_action_type == 'touch':
        action_type = 'touch'
      elif 'long' in raw_action_type:
        action_type = 'long_touch'
      elif 'up' in raw_action_type.lower():
        action_type = 'scroll up'
      elif 'down' in raw_action_type.lower():
        action_type = 'scroll down'
      elif 'input' in raw_action_type.lower():
        action_type = 'set_text'
      elif 'select' in raw_action_type.lower():
        action_type = 'select'
      else:
        action_type = raw_action_type

      input_text = answer_dict[
          'input_text'] if 'input_text' in answer_dict else ''
      if input_text in ['N/A', 'n/a', 'None', 'none', 'null', 'Null', 'NULL']:
        input_text = ''

      return id, action_type, input_text, ui_function, finished

    def get_action_desc(action_type, selected_element, input_text=None):

      if action_type in ['touch', 'long_touch', 'select']:
        action_desc = f"{action_type}: {selected_element}"

      elif action_type in ['scroll up', 'scroll down']:
        action_desc = f"{action_type}"

      elif action_type == 'set_text':
        action_desc = f"Touch: {selected_element} Input_text: {input_text}"

      else:
        action_desc = f"{action_type}: {selected_element}"

      return action_desc

    print('-' * 30, '\n', answer, '\n', '-' * 30)
    if isinstance(answer, str):
      answer = self.convert_gpt_answer_to_json(answer)
    # pdb.set_trace()
    id, action_type, input_text, ui_function, finished = llm_action_extract(
        answer)

    if isinstance(id, str):
      # if LLM returns the target element's bbox
      new_id = -1
      for ele_id, element_desc in element_map.items():
        if id in element_desc:
          new_id = ele_id
      id = new_id

    # TODO: if the id is -1, prompt gpt to think about it carefully
    if finished:
      print("finished task")
      return {"action_type": "status", "goal_status": "complete"}
    if id == -1:
      print("task is infeasible")
      return {"action_type": "status", "goal_status": "infeasible"}

    action_desc = get_action_desc(action_type,
                                    element_map[id].full_desc, input_text)
    self.former_steps.append({'UI': ui_function, 'action': action_desc})
    try:
      return Utils.pack_action(action_type, id, input_text)
    except:
      print("Unexpected error")
      return None

  def convert_gpt_answer_to_json(self,
                                 answer,
                                 default_value={'default': 'format wrong'}):
    import ast
    convert_prompt = f"Convert the following data into JSON format, ensuring it's valid for Python parsing (pay attention to single/double quotes in the strings. \n\ndata:\n{answer}\n\n**Please do not output any content other than the JSON format.**"
    try:
      converted_answer = ast.literal_eval(answer)
    except:
      print('*' * 10, 'converting', '*' * 10, '\n', answer, '\n', '*' * 50)
      converted_answer, _ = self.llm.predict(convert_prompt)
      print('*' * 10, 'converted v1', '*' * 10, '\n', converted_answer, '\n',
            '*' * 10)
      if isinstance(converted_answer, str):
        try:
          converted_answer = ast.literal_eval(converted_answer)
        except:
          new_convert = f'''Convert the following data into JSON format, ensuring it's valid for Python parsing (pay attention to single/double quotes in the strings). \n\ndata:\n{answer}\n\nThe former answer you returned:\n{converted_answer}\nis wrong and can not be parsed in python. Please check it and convert it properly! \n\n**Please do not output any content other than the JSON format!!!**'''
          converted_answer, _ = self.llm.predict(new_convert)
          print('*' * 10, 'converted v2', '*' * 10, '\n', converted_answer,
                '\n', '*' * 10)
          if isinstance(converted_answer, str):
            try:
              converted_answer = ast.literal_eval(converted_answer)
            except:
              return default_value
    return converted_answer
