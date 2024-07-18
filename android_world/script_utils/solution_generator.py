import ast
import json
import os
from android_world.script_utils.gen_dependency_tree import get_semantic_dependencies
from android_world.script_utils import tools


class SolutionGenerator:

  def __init__(self, apis_path, llm):
    self.apis_data = tools.load_json_file(apis_path)
    self.llm = llm

  def format_all_apis(self, enable_dependency):
    # apis_data = json.load(open(os.path.join(self.apis_folder_path, 'apis.json')))
    apis_description = ''
    api_names = []
    for _, v in self.apis_data.items():
      for e in v:
        if e["name"] == "" or e["name"] in api_names:
          continue
        api_names.append(e["name"])
        name = e["name"]
        if enable_dependency:
          dep = e['dependency']
          semantic_dep = get_semantic_dependencies(dep)
        desc = e["desc"]
        func = e["func"]

        if enable_dependency:
          apis_description += f'element: {name}\n\tDescription: {desc}\n\t Function: {func} \n\tDependency: {semantic_dep}. \n\n'
        else:
          apis_description += f'element: {name}\n\tDescription: {desc}\n\t Function: {func} \n\n'
    print(f'Generated description for {len(api_names)} APIs')
    return apis_description

  def make_prompt(self, task, app_name, state_ui_elements=None):

    # if first_state_apis is not None:
    #     first_ui_apis = f'\nThe first state of the app has the following important UI elements: \n{first_state_apis}\n\n'
    # else:
    #     first_ui_apis = ''
    ui_apis = '\n'.join(state_ui_elements)
    formatted_apis = self.format_all_apis(enable_dependency=False)

    prompt = f'''A {app_name} app in smartphone has the following important UI elements:

{formatted_apis}

You will be asked to complete tasks by writing scripts to manipulate the above elements.
In the script, except for the common python control flow (for, if-else, function def/calls, etc.), you can use the following APIs:
- tap(<element_selector>): tap on the element. Almost all elements can be taped. If an element's attribute checked=false or selected=false, tapping it can make it checked or selected, vice versa.
- long_tap(<element_selector>): long tap the element. 
- set_text(<element_selector>, <text>): set the text of the element to <text>. Only editable text fields can be set text.
- scroll(<element_selector>, <direction>): scroll the UI element in the specified direction, and direction is a str from "up", 'down", "left", "right". e.g. scroll($scroll_settings_page, "down"
- get_text(<element_selector>): return the text of the element as a string.
- get_attributes(<element_selector>): return the attributes of the element as a dict, dict keys include "selected", "checked", "scrollable", dict values are boolean. eg. get_attributes($files[3])["selected"].
- back(): close the current window


The <element_selector> primitive is used to select an element, possible ways of selection include:
- $<element id>, eg. $settings_button
- <element_list>[<idx>]: the idx-th in the element list. eg. $my_items[1]

The <element_list> primitive is used to select a list of elements, possible ways of selection include:
- <element_selector>: the items in the list element identified by <element_selector>. eg. $my_items
- <element_list>.match(<text or attribute dict>): the elements in the element list that match the given text or attribute dict. eg. $my_items.match("key words") or $my_items.match({{"selected": true}})
You can use len(<element_list>) to get the total number of items in an element list.

The current UI has the following important UI elements:
{ui_apis}

Now I will give you a task, you should return the python script to complete the task.
The task is:
    {task}

Your answer should follow this JSON format:

{{
    'Plan': '<the plan to complete the task from the first UI>',
    'Script': '<the Python script to complete the task>',
}}

**Note that the script is a string of python code and should only output the JSON content.**
'''
    return prompt

  def get_solution(self,
                   app_name,
                   prompt_answer_path,
                   task,
                   ui_elements,
                   enable_dependency=False,
                   model_name='gpt-3.5-turbo'):
    # formatted_apis = self.format_all_apis(enable_dependency)
    prompt = self.make_prompt(task=task,
                              app_name=app_name,
                              state_ui_elements=ui_elements)
    answer = tools.query_gpt(prompt=prompt, model=model_name)
    tools.dump_json_file(prompt_answer_path, {
        'prompt': prompt,
        'answer': answer
    })
    answer = tools.convert_gpt_answer_to_json(answer,
                                              model_name=model_name,
                                              default_value={
                                                  'Plan': '',
                                                  'Script': ''
                                              })
    if 'Script' in answer.keys():
      return answer['Script']
    else:
      return answer['script']
