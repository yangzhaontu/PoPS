from configs import PruneCartpoleConfig as student_config
from configs import CartpoleConfig as dense_config
from model import CartPoleDQNTarget, StudentCartpole
from utils.plot_utils import plot_graph
from utils.logger_utils import get_logger
from Cartpole.evaluate_cartpole import evaluate_cartepole as evaluate
from train import fit_supervised
from Cartpole.accumulate_experience_cartpole import accumulate_experience_cartpole
from prune import iterative_pruning_policy_distilliation
from argparse import ArgumentParser
from utils.tensorflow_utils import calculate_redundancy
from collections import deque
from Cartpole.copy_weights_cartpole import copy_weights
FLAGS = 0


def check_convergence(info):
    diff_temp = []
    for i in range(len(info) - 1):
        diff_temp.append(info[i] - info[i+1])
    mean_diff = sum(diff_temp) / len(diff_temp)
    if mean_diff < 0.05:  # a change of less then 1.0 percent in size counts as a converged model
        return True
    else:
        return False


def main():
    #   ----------------- Setting initial variables Section -----------------
    logger = get_logger(FLAGS.PoPS_dir + "/PoPS_ITERATIVE")
    logger.info(" ------------- START: -------------")
    logger.info("Setting initial data structures")
    accuracy_vs_size = [[], []]
    logger.info("Loading models")
    teacher = CartPoleDQNTarget(input_size=dense_config.input_size, output_size=dense_config.output_size)
    teacher.load_model(path=FLAGS.teacher_path)  # load teacher
    logger.info("----- evaluating teacher -----")
    print("----- evaluating teacher -----")
    teacher_score = evaluate(agent=teacher, n_epoch=FLAGS.eval_epochs)
    logger.info("----- teacher evaluated with {} ------".format(teacher_score))
    print("----- teacher evaluated with {} -----".format(teacher_score))
    prune_step_path = FLAGS.PoPS_dir + "/prune_step_"
    policy_step_path = FLAGS.PoPS_dir + "/policy_step_"
    initial_path = policy_step_path + "0"
    logger.info("creating policy step 0 model, which is identical in size to the original model")
    copy_weights(output_path=initial_path, teacher_path=FLAGS.teacher_path)  # inorder to create the initial model
    compressed_agent = StudentCartpole(input_size=student_config.input_size,
                                   output_size=student_config.output_size,
                                   model_path=initial_path,
                                   tau=student_config.tau,
                                   pruning_freq=student_config.pruning_freq,
                                   sparsity_end=student_config.sparsity_end,
                                   target_sparsity=student_config.target_sparsity)
    compressed_agent.load_model()
    initial_size = compressed_agent.get_number_of_nnz_params()
    accuracy_vs_size[0].append(initial_size)
    accuracy_vs_size[1].append(teacher_score)
    initial_number_of_params_at_each_layer = compressed_agent.get_number_of_nnz_params_per_layer()
    initial_number_of_nnz = sum(initial_number_of_params_at_each_layer)
    converge = False
    iteration = 0
    convergence_information = deque(maxlen=2)
    convergence_information.append(100)
    precent = 100
    arch_type = 0
    last_measure = initial_size
    while not converge:
        iteration += 1
        print("-----  Pruning Step {} -----".format(iteration))
        logger.info(" -----  Pruning Step {} -----".format(iteration))
        path_to_save_pruned_model = prune_step_path + str(iteration)
        #   ----------------- Pruning Section -----------------
        if arch_type == 2:
            arch_type = 3  # special arch_type for prune-oriented learning rate
        sparsity_vs_accuracy = iterative_pruning_policy_distilliation(logger=logger, agent=compressed_agent,
                                                                                  target_agent=teacher,
                                                                                  iterations=FLAGS.iterations,
                                                                                  config=student_config,
                                                                                  best_path=path_to_save_pruned_model,
                                                                                  arch_type=arch_type,
                                                                                  lower_bound=student_config.LOWER_BOUND,
                                                                                  accumulate_experience_fn=accumulate_experience_cartpole,
                                                                                  evaluate_fn=evaluate,
                                                                                  objective_score=student_config.OBJECTIVE_SCORE)
        plot_graph(data=sparsity_vs_accuracy, name=FLAGS.PoPS_dir + "/initial size {}%,  Pruning_step number {}"
                   .format(precent, iteration), figure_num=iteration)

        # loading model which has reasonable score with the highest sparsity
        compressed_agent.load_model(path_to_save_pruned_model)
        #   ----------------- Measuring redundancy Section -----------------
        # the amount of parameters that are not zero at each layer
        nnz_params_at_each_layer = compressed_agent.get_number_of_nnz_params_per_layer()
        # the amount of parameters that are not zero
        nnz_params = sum(nnz_params_at_each_layer)
        # redundancy is the parameters we dont need, nnz_params / initial is the params we need the opposite
        redundancy = (1 - nnz_params / initial_number_of_nnz) * 100
        print("-----  Pruning Step {} finished, got {}% redundancy in net params -----"
              .format(iteration, redundancy))
        logger.info("-----  Pruning Step {} finished , got {}% redundancy in net params -----"
                    .format(iteration, redundancy))
        logger.info("-----  Pruning Step {} finished with {} NNZ params at each layer"
                    .format(iteration, nnz_params_at_each_layer))
        print(" -----  Evaluating redundancy at each layer Step {}-----".format(iteration))
        logger.info(" -----  Evaluating redundancy at each layer Step {} -----".format(iteration))
        redundancy_at_each_layer = calculate_redundancy(initial_nnz_params=initial_number_of_params_at_each_layer,
                                                        next_nnz_params=nnz_params_at_each_layer)
        logger.info("----- redundancy for each layer at step {} is {} -----".format(iteration, redundancy_at_each_layer))
        if iteration == 1:
            redundancy_at_each_layer = [0.83984375, 0.8346405029296875, 0.83795166015625, 0.83984375]
        #   ----------------- Policy distillation Section -----------------
        print(" -----  Creating Model with size according to the redundancy at each layer ----- ")
        logger.info("----- Creating Model with size according to the redundancy at each layer -----")
        policy_distilled_path = policy_step_path + str(iteration)
        # creating the compact model where every layer size is determined by the redundancy measure
        compressed_agent = StudentCartpole(input_size=student_config.input_size,
                                           output_size=student_config.output_size,
                                           model_path=policy_distilled_path,
                                           tau=student_config.tau,
                                           redundancy=redundancy_at_each_layer,
                                           pruning_freq=student_config.pruning_freq,
                                           sparsity_end=student_config.sparsity_end,
                                           target_sparsity=student_config.target_sparsity,
                                           last_measure=last_measure)
        nnz_params_at_each_layer = compressed_agent.get_number_of_nnz_params_per_layer()
        logger.info("-----  Step {} ,Created Model with {} NNZ params at each layer"
                    .format(iteration, nnz_params_at_each_layer))
        iterative_size = compressed_agent.get_number_of_nnz_params()
        last_measure = iterative_size
        precent = (iterative_size / initial_size) * 100
        convergence_information.append(precent)
        print(" ----- Step {}, Created Model with size {} which is {}% from original size ----- "
              .format(iteration, iterative_size, precent))
        logger.info("----- Created Model with size {} which is {}% from original size -----"
                    .format(iterative_size, precent))
        # scheduling the right learning rate for the size of the model
        if precent > 40:
            arch_type = 0
        elif 10 <= precent <= 40:
            arch_type = 1
        else:
            arch_type = 2
        print(" -----  policy distilling Step {} ----- ".format(iteration))
        logger.info("----- policy distilling Step {} -----".format(iteration))
        fit_supervised(logger=logger, arch_type=arch_type, student=compressed_agent, teacher=teacher,
                           n_epochs=FLAGS.n_epoch, evaluate_fn=evaluate,
                           accumulate_experience_fn=accumulate_experience_cartpole,
                           lower_score_bound=student_config.LOWER_BOUND, objective_score=student_config.OBJECTIVE_SCORE)

        policy_distilled_score = evaluate(agent=compressed_agent, n_epoch=FLAGS.eval_epochs)
        compressed_agent.reset_global_step()
        print(" -----  policy distilling Step {} finished  with score {} ----- "
              .format(iteration, policy_distilled_score))
        logger.info("----- policy distilling Step {} finished with score {}  -----"
                    .format(iteration, policy_distilled_score))
        # checking convergence
        converge = check_convergence(convergence_information)
        # for debugging purposes
        accuracy_vs_size[0].append(iterative_size)
        accuracy_vs_size[1].append(policy_distilled_score)

    plot_graph(data=accuracy_vs_size, name=FLAGS.PoPS_dir + "/accuracy_vs_size", figure_num=iteration + 1, xaxis='NNZ params', yaxis='Accuracy')


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument(
        '--teacher_path',
        type=str,
        default=dense_config.ready_path,
        help=' path where to load initial model.')
    parser.add_argument(
        '--PoPS_dir',
        type=str,
        default=student_config.iterative_PoPS,
        help='Results Directory.')
    parser.add_argument(
        '--model_path',
        type=str,
        default=dense_config.model_path,
        help=' Directory where to load initial model.')
    parser.add_argument(
        '--n_epoch',
        type=int,
        default=student_config.n_epoch,
        help='number of epoches to do policy distillation')
    parser.add_argument(
        '--iterations',
        type=int,
        default=student_config.n_epoch,
        help='number of iteration to do pruning')
    parser.add_argument(
        '--batch_size',
        type=int,
        default=dense_config.n_epoch,
        help='number of epoches')
    parser.add_argument(
        '--eval_epochs',
        type=int,
        default=100,
        help='number of epoches to evaluate the models during the process')
    FLAGS, unparsed = parser.parse_known_args()
    main()
